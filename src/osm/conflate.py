"""CAGIS Street Centerline conflation.

Ground-truths OSM ways against authoritative Hamilton County street
centerlines (CAGIS Open Data Hub, FeatureServer/26). Match results are
attached to each OSM way as ``cagis_match`` and used by the review/changeset
layers to graduate heuristic candidates into evidence-backed fixes.

Source: CAGIS Open Data Hub, Hamilton County, Ohio
        https://cagisonline.hamilton-co.org/cagisonline/
        License: "as is" with required attribution + disclaimer.
        Quarterly updated.

Dependency note: this module needs ``shapely>=2.0``. If shapely is not
importable (older environments, broken wheel on Windows, etc.) we degrade
gracefully — :func:`build_index` returns an empty stub, :func:`match_way`
returns ``None`` for everything, and the rest of the pipeline keeps working.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from osm._geometry import (
    directed_hausdorff_meters as _directed_hausdorff_meters,
)
from osm._geometry import (
    direction_alignment as _direction_alignment,
)
from osm._geometry import (
    line_unit_vector as _line_unit_vector,
)
from osm._geometry import (
    line_unit_vector_lonlat as _line_unit_vector_lonlat,
)
from osm._geometry import (
    meters_to_degrees as _meters_to_degrees_helper,
)
from osm._geometry import (
    min_dist_to_polyline as _min_dist_to_polyline,
)
from osm._geometry import (
    name_similarity as _name_similarity,
)
from osm._geometry import (
    polyline_length_m as _polyline_length_m,
)
from osm.cache import bbox_hash as _bbox_hash_helper
from osm.cache import cache_path as _bbox_cache_path
from osm.cache import is_cache_fresh
from osm.config import CONFIG_DIR
from osm.geo import norm_name
from osm.zones import ZONES

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAGIS_FEATURE_SERVER = (
    "https://services.arcgis.com/JyZag7oO4NteHGiq/arcgis/rest/services/"
    "Open_Data/FeatureServer/26"
)
CAGIS_QUERY_URL = f"{CAGIS_FEATURE_SERVER}/query"
CAGIS_FEATURE_URL_TMPL = f"{CAGIS_FEATURE_SERVER}/{{id}}"
CAGIS_PAGE_SIZE = 2000
CAGIS_CACHE_TTL_DAYS = 90
CAGIS_CACHE_DIR = CONFIG_DIR / "cagis_cache"

CAGIS_ATTRIBUTION = (
    "Source: CAGIS Open Data Hub, Hamilton County, Ohio "
    "(https://cagisonline.hamilton-co.org/) — used as-is per license."
)

# Match thresholds
BUFFER_M = 30.0
HIGH_CONFIDENCE = 0.85
REVIEW_CONFIDENCE = 0.6

# Phase 2b nearest-neighbor fallback. When the STRtree buffer query
# returns no candidates within BUFFER_M, look up the absolutely nearest
# CAGIS centerline. If its directed Hausdorff is within FALLBACK_BUFFER_M,
# score it normally but cap the confidence at REVIEW_CONFIDENCE so it
# never auto-submits — only surfaces in the human-review queue. The cap
# is the plan's "≤0.6 ceiling" guardrail.
#
# Justified by Phase 2b F1 nearest-distance histograms: in Blue Ash and
# Northgate, hundreds of ways sit just past 30m. In Forest Park (median
# 1.4km) the cap-by-distance prevents the fallback from generating noise
# from the zone-polygon bleed into Butler County.
FALLBACK_BUFFER_M = 100.0

# Confidence-score weights. Single source of truth for the matcher AND the
# Phase 2a diagnostic — adjusting these here keeps both in sync.
W_NAME = 0.5
W_GEOMETRY = 0.3
W_DIRECTION = 0.2
# Sum without the direction term; used by the F4 (direction-drag) attribution
# to ask "would this match clear REVIEW_CONFIDENCE if direction were perfect?"
W_NON_DIRECTION = W_NAME + W_GEOMETRY

# Phase 2a diagnostic thresholds. These do NOT change scoring behaviour;
# they only classify *why* a way landed in its current confidence bucket.
DIAG_NAME_FAIL_THRESHOLD = 0.5      # name_similarity below this is "name fail"
DIAG_SHORT_WAY_M = 50.0             # ways shorter than this have noisy direction
DIAG_DIAGNOSTIC_BUFFER_M = BUFFER_M  # buffer used for candidate enumeration

# Bucket labels for diagnose_match() / write_baseline_manifest().
BUCKET_MATCHED_HIGH = "MATCHED_HIGH"          # confidence >= 0.85
BUCKET_MATCHED_REVIEW = "MATCHED_REVIEW"      # in-buffer, 0.6 <= confidence < 0.85
BUCKET_MATCHED_FALLBACK_REVIEW = "MATCHED_FALLBACK_REVIEW"  # out-of-buffer fallback, capped at REVIEW
BUCKET_F1_NO_CANDIDATE = "F1_NO_CANDIDATE"    # nothing within FALLBACK_BUFFER_M either
BUCKET_F2_NAME_FAIL = "F2_NAME_FAIL"          # geometry passes, name drags
BUCKET_F3_GEOMETRY_FAIL = "F3_GEOMETRY_FAIL"  # candidates exist, all haus > BUFFER_M
BUCKET_F4_DIRECTION_DRAG = "F4_DIRECTION_DRAG"  # short way; direction term killed it
BUCKET_MIXED_LOW = "MIXED_LOW"                # confidence < 0.6 with no single dominant cause

# CAGIS schema (verified by probing the FeatureServer 2026-05-07).
# Real field names — do not rename without re-probing.
F_OBJECTID = "OBJECTID"
F_LABEL = "STRLABEL"
F_MAPLABEL = "MAPLABEL"
F_TRVL_DIR = "TRVL_DIR"
F_CLASS = "CLASS"
F_SPEED = "SPEEDLIMIT"
F_NAVIGABLE = "NAVIGABLE"
F_SEGTYPE = "SEGTYPE"

# CAGIS CLASS code → coarse functional-class label.
# Codes 1=interstate/freeway, 2=arterial, 3=collector, 5=local, 6=ramp.
CAGIS_FUNCTIONAL_CLASS: dict[int, str] = {
    1: "interstate",
    2: "arterial",
    3: "collector",
    4: "minor_collector",
    5: "local",
    6: "ramp",
    7: "service",
}


def _functional_class_label(value: Any) -> str | None:
    """Map a CAGIS CLASS code (possibly missing/garbage) to a coarse label."""
    try:
        code = int(value)
    except (TypeError, ValueError):
        return None
    return CAGIS_FUNCTIONAL_CLASS.get(code)


# ---------------------------------------------------------------------------
# Optional shapely import — graceful degradation if unavailable
# ---------------------------------------------------------------------------

try:
    from shapely.geometry import LineString, Point  # type: ignore[import-not-found]
    from shapely.strtree import STRtree  # type: ignore[import-not-found]
    SHAPELY_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    log.warning(
        "shapely>=2.0 not importable (%s); CAGIS conflation will be skipped. "
        "Install with: pip install 'shapely>=2.0'",
        exc,
    )
    LineString = None  # type: ignore[assignment,misc]
    Point = None  # type: ignore[assignment,misc]
    STRtree = None  # type: ignore[assignment,misc]
    SHAPELY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _bbox_hash(bbox: tuple[float, float, float, float]) -> str:
    """Stable short hash for cache filenames keyed by bbox.

    Thin wrapper around :func:`osm.cache.bbox_hash` preserved as an internal
    name so existing imports in this module keep working.
    """
    return _bbox_hash_helper(bbox)


def _cache_path(bbox: tuple[float, float, float, float]) -> Path:
    # CAGIS uses .geojson extension because the FeatureServer returns GeoJSON;
    # other modules use .json.
    return _bbox_cache_path(
        CAGIS_CACHE_DIR, bbox, prefix="centerlines", suffix="geojson"
    )


def _cache_fresh(path: Path) -> bool:
    return is_cache_fresh(path, CAGIS_CACHE_TTL_DAYS * 86_400)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_cagis_centerlines(
    bbox: tuple[float, float, float, float],
    *,
    force_refresh: bool = False,
    timeout: int = 60,
) -> list[dict]:
    """Fetch CAGIS Street Centerlines intersecting a (south, west, north, east) bbox.

    Returns a list of GeoJSON-like dicts with ``geometry`` (LineString) and
    ``properties``. Paginates the FeatureServer until the result set is
    exhausted (CAGIS caps at 2000 features per page).

    Cached on disk under ``~/.config/osm/cagis_cache/`` keyed by bbox hash;
    cache TTL is 90 days. Pass ``force_refresh=True`` to bypass.
    """
    south, west, north, east = bbox
    cache_path = _cache_path(bbox)

    if not force_refresh and _cache_fresh(cache_path):
        try:
            with cache_path.open("r", encoding="utf-8") as fh:
                cached = json.load(fh)
            log.info("CAGIS: loaded %d feature(s) from cache %s",
                     len(cached), cache_path.name)
            return cached
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("CAGIS cache %s unreadable (%s); re-fetching.",
                        cache_path.name, exc)

    features: list[dict] = []
    offset = 0
    page = 0
    while True:
        page += 1
        params = {
            "where": "1=1",
            "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
            "resultOffset": str(offset),
            "resultRecordCount": str(CAGIS_PAGE_SIZE),
        }
        log.info("CAGIS: fetching page %d (offset=%d)…", page, offset)
        try:
            resp = requests.get(CAGIS_QUERY_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("CAGIS fetch failed on page %d: %s", page, exc)
            break

        page_features = data.get("features") or []
        features.extend(page_features)
        if not page_features:
            break
        # The geojson endpoint flag is `exceededTransferLimit` in some
        # versions, missing in others — fall back to "did we get a full page".
        if data.get("exceededTransferLimit") is True:
            offset += len(page_features)
            continue
        if len(page_features) >= CAGIS_PAGE_SIZE:
            offset += len(page_features)
            continue
        break

    log.info("CAGIS: fetched %d feature(s) for bbox %s", len(features), bbox)

    # Persist to cache (best-effort; never fatal).
    try:
        CAGIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump(features, fh, ensure_ascii=False)
    except OSError as exc:
        log.warning("Could not write CAGIS cache %s: %s", cache_path, exc)

    return features


def load_cagis_for_zone(
    zone_key: str, *, force_refresh: bool = False
) -> list[dict]:
    """Resolve zone bbox via :mod:`osm.zones` then fetch its CAGIS centerlines."""
    if zone_key not in ZONES:
        raise KeyError(f"Unknown zone {zone_key!r}; choices: {list(ZONES)}")
    bbox = tuple(ZONES[zone_key]["bbox"])
    return fetch_cagis_centerlines(bbox, force_refresh=force_refresh)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Index + match
# ---------------------------------------------------------------------------

@dataclass
class _CagisRecord:
    """One indexed CAGIS centerline ready for matching."""
    cagis_id: int | str
    name: str | None
    name_norm: str | None
    oneway: str  # "yes" | "-1" | "no"
    functional_class: str | None
    speed_limit: int | None
    geometry_lonlat: list[tuple[float, float]]
    line: Any  # shapely LineString
    raw_props: dict


def _decode_oneway(trvl_dir: Any) -> str:
    """Translate CAGIS TRVL_DIR int into OSM-style oneway value.

    TRVL_DIR is the canonical CAGIS field for direction of travel:
        0  → both directions  → ``"no"``
        1  → forward (with digitisation order) → ``"yes"``
        -1 → reverse → ``"-1"``
    """
    try:
        v = int(trvl_dir)
    except (TypeError, ValueError):
        return "no"
    if v == 1:
        return "yes"
    if v == -1:
        return "-1"
    return "no"


def _coerce_speed(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        s = int(round(float(value)))
        return s if s > 0 else None
    except (TypeError, ValueError):
        return None


def _record_from_feature(feat: dict) -> _CagisRecord | None:
    """Build a :class:`_CagisRecord` from a CAGIS GeoJSON feature, or None
    if the geometry is unusable."""
    if not SHAPELY_AVAILABLE:
        return None
    geom = feat.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    # CAGIS lines are usually LineString but a few are MultiLineString.
    rings: list[list[tuple[float, float]]] = []
    if gtype == "LineString":
        rings = [[(float(x), float(y)) for x, y, *_ in coords if x is not None]]
    elif gtype == "MultiLineString":
        for part in coords:
            rings.append([(float(x), float(y)) for x, y, *_ in part if x is not None])
    if not rings:
        return None
    # Use the longest ring for matching (prevents matching tiny stubs of
    # multi-line records).
    main = max(rings, key=len)
    if len(main) < 2:
        return None

    props = feat.get("properties") or feat.get("attributes") or {}
    label = props.get(F_LABEL) or props.get(F_MAPLABEL)
    cagis_id = props.get(F_OBJECTID)
    if cagis_id is None:
        cagis_id = props.get("FEATUREID") or "?"

    try:
        line = LineString(main)
    except Exception as exc:  # noqa: BLE001
        log.debug("CAGIS feature %s has invalid geometry: %s", cagis_id, exc)
        return None

    return _CagisRecord(
        cagis_id=cagis_id,
        name=label,
        name_norm=norm_name(label),
        oneway=_decode_oneway(props.get(F_TRVL_DIR)),
        functional_class=_functional_class_label(props.get(F_CLASS)),
        speed_limit=_coerce_speed(props.get(F_SPEED)),
        geometry_lonlat=main,
        line=line,
        raw_props=props,
    )


class ConflationIndex:
    """Spatial index over CAGIS centerlines for fast OSM-way matching.

    When shapely is unavailable, every method returns empty/None — the
    pipeline still runs, just with no CAGIS evidence attached.
    """

    def __init__(self, records: list[_CagisRecord]):
        self.records = records
        self._tree = None
        self._line_records: list[_CagisRecord] = []
        if SHAPELY_AVAILABLE and records:
            geoms = [r.line for r in records]
            self._line_records = list(records)
            try:
                self._tree = STRtree(geoms)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not build STRtree: %s", exc)
                self._tree = None

    def __len__(self) -> int:
        return len(self.records)

    @property
    def available(self) -> bool:
        return SHAPELY_AVAILABLE and self._tree is not None

    def _candidates(self, geom: Any, buffer_deg: float) -> list[_CagisRecord]:
        if self._tree is None:
            return []
        try:
            idx_array = self._tree.query(geom.buffer(buffer_deg))
        except Exception as exc:  # noqa: BLE001
            log.debug("STRtree query failed: %s", exc)
            return []
        out: list[_CagisRecord] = []
        for raw in idx_array:
            i = int(raw)
            if 0 <= i < len(self._line_records):
                out.append(self._line_records[i])
        return out

    def within_buffer(self, line: Any, meters: float) -> list[_CagisRecord]:
        if self._tree is None:
            return []
        buf = _meters_to_degrees(line, meters)
        return self._candidates(line, buf)

    def nearest(self, point_lonlat: tuple[float, float]) -> _CagisRecord | None:
        if self._tree is None:
            return None
        try:
            p = Point(point_lonlat)
            i = self._tree.nearest(p)
            if i is None:
                return None
            return self._line_records[int(i)]
        except Exception:  # noqa: BLE001
            return None

    def match(
        self, osm_geometry: list[list[float]], osm_name: str | None
    ) -> dict | None:
        """Look up the best CAGIS centerline for an OSM way.

        ``osm_geometry`` is a list of ``[lat, lon]`` pairs (the in-pipeline
        format). Returns a match dict (see :func:`match_way`) or ``None``.
        """
        if not self.available:
            return None
        if not osm_geometry or len(osm_geometry) < 2:
            return None

        try:
            # OSM stores [lat, lon]; shapely needs (lon, lat).
            line = LineString([(p[1], p[0]) for p in osm_geometry])
        except Exception:  # noqa: BLE001
            return None

        osm_norm = norm_name(osm_name)
        osm_vec = _line_unit_vector(osm_geometry)

        candidates = self.within_buffer(line, BUFFER_M)
        if not candidates:
            # Phase 2b fallback: try nearest. Confidence is capped at
            # REVIEW_CONFIDENCE so the result can populate the human-review
            # queue but never auto-submit.
            fb = self._fallback_score(osm_geometry, osm_norm, osm_vec, line)
            if fb is None:
                return None
            fb_conf, fb_rec, fb_name_sim, fb_haus, _fb_dir = fb
            return self._build_match_result(
                fb_conf, fb_rec, fb_name_sim, fb_haus, osm_norm,
                via_fallback=True,
            )

        best: tuple[float, _CagisRecord, float, float, float] | None = None
        for rec in candidates:
            haus = _directed_hausdorff_meters(osm_geometry, rec.geometry_lonlat)
            if haus is None or haus > BUFFER_M:
                # Even with bbox proximity, geometry may be too far.
                continue
            name_sim = _name_similarity(osm_norm, rec.name_norm)
            cagis_vec = _line_unit_vector_lonlat(rec.geometry_lonlat)
            dir_align = _direction_alignment(osm_vec, cagis_vec)
            geom_overlap = max(0.0, min(1.0, 1.0 - haus / BUFFER_M))
            confidence = (
                W_NAME * name_sim
                + W_GEOMETRY * geom_overlap
                + W_DIRECTION * dir_align
            )
            if best is None or confidence > best[0]:
                best = (confidence, rec, name_sim, haus, dir_align)

        if best is None:
            # All in-buffer candidates failed Hausdorff (rare with directed
            # metric, but possible). Try the same fallback path.
            fb2 = self._fallback_score(osm_geometry, osm_norm, osm_vec, line)
            if fb2 is None:
                return None
            fb2_conf, fb2_rec, fb2_name_sim, fb2_haus, _fb2_dir = fb2
            return self._build_match_result(
                fb2_conf, fb2_rec, fb2_name_sim, fb2_haus, osm_norm,
                via_fallback=True,
            )

        b_conf, b_rec, b_name_sim, b_haus, _b_dir = best
        return self._build_match_result(
            b_conf, b_rec, b_name_sim, b_haus, osm_norm, via_fallback=False,
        )

    def _fallback_score(
        self,
        osm_geometry: list[list[float]],
        osm_norm: str | None,
        osm_vec: tuple[float, float] | None,
        line: Any,
    ) -> tuple[float, _CagisRecord, float, float, float] | None:
        """Score the absolutely nearest CAGIS centerline, capped at REVIEW.

        Returns None if no nearest exists or it's beyond FALLBACK_BUFFER_M.
        Confidence in the returned tuple is capped at REVIEW_CONFIDENCE.
        """
        if not osm_geometry:
            return None
        # nearest() takes (lon, lat).
        try:
            first_pt_lonlat = (osm_geometry[0][1], osm_geometry[0][0])
        except (IndexError, TypeError):
            return None
        nearest_rec = self.nearest(first_pt_lonlat)
        if nearest_rec is None:
            return None
        haus = _directed_hausdorff_meters(osm_geometry, nearest_rec.geometry_lonlat)
        if haus is None or haus > FALLBACK_BUFFER_M:
            return None
        name_sim = _name_similarity(osm_norm, nearest_rec.name_norm)
        cagis_vec = _line_unit_vector_lonlat(nearest_rec.geometry_lonlat)
        dir_align = _direction_alignment(osm_vec, cagis_vec)
        # Geometry overlap uses the wider FALLBACK denominator since the
        # candidate is by definition past the normal buffer.
        geom_overlap = max(0.0, min(1.0, 1.0 - haus / FALLBACK_BUFFER_M))
        raw_confidence = (
            W_NAME * name_sim
            + W_GEOMETRY * geom_overlap
            + W_DIRECTION * dir_align
        )
        # Cap at REVIEW_CONFIDENCE — fallback hits never auto-submit.
        confidence = min(raw_confidence, REVIEW_CONFIDENCE)
        return (confidence, nearest_rec, name_sim, haus, dir_align)

    def _build_match_result(
        self,
        confidence: float,
        rec: _CagisRecord,
        name_sim: float,
        haus: float,
        osm_norm: str | None,
        *,
        via_fallback: bool,
    ) -> dict:
        return {
            "cagis_id": rec.cagis_id,
            "cagis_name": rec.name,
            "cagis_oneway": rec.oneway,
            "cagis_functional_class": rec.functional_class,
            "cagis_speed_limit": rec.speed_limit,
            "confidence": round(confidence, 4),
            "name_similarity": round(name_sim, 4),
            "hausdorff_m": round(haus, 2),
            "name_match": bool(
                osm_norm is not None
                and rec.name_norm is not None
                and name_sim >= 0.85
            ),
            "via_fallback": via_fallback,
        }

    def diagnose_match(
        self, osm_geometry: list[list[float]], osm_name: str | None
    ) -> dict:
        """Phase 2a: per-way diagnostic that classifies match outcome.

        Read-only. Does NOT change scoring or what :meth:`match` returns.
        Always returns a dict with a ``bucket`` key plus enough metric
        context to attribute the outcome.

        Buckets:
            MATCHED_HIGH       — confidence >= HIGH_CONFIDENCE (auto-submit)
            MATCHED_REVIEW     — REVIEW_CONFIDENCE <= confidence < HIGH
            F1_NO_CANDIDATE    — STRtree returned nothing within BUFFER_M
            F2_NAME_FAIL       — best candidate within BUFFER_M but name drags
            F3_GEOMETRY_FAIL   — candidates within buffer; all Hausdorff > BUFFER_M
            F4_DIRECTION_DRAG  — short way (< DIAG_SHORT_WAY_M); direction term
                                 alone pushed confidence under REVIEW_CONFIDENCE
            MIXED_LOW          — confidence < REVIEW_CONFIDENCE with no
                                 dominant single cause
        """
        way_length_m = round(_polyline_length_m(osm_geometry), 2)
        diag: dict[str, Any] = {
            "bucket": BUCKET_F1_NO_CANDIDATE,
            "confidence": None,
            "name_similarity": None,
            "hausdorff_m": None,
            "direction_alignment": None,
            "candidates_within_buffer": 0,
            "nearest_distance_m": None,
            "way_length_m": way_length_m,
            "best_match": None,
        }

        if not self.available:
            diag["bucket"] = BUCKET_F1_NO_CANDIDATE
            diag["nearest_distance_m"] = None
            return diag
        if not osm_geometry or len(osm_geometry) < 2:
            return diag

        try:
            line = LineString([(p[1], p[0]) for p in osm_geometry])
        except Exception:  # noqa: BLE001
            return diag

        # Compute name/direction context up front so the fallback branch
        # below can reuse them.
        osm_norm = norm_name(osm_name)
        osm_vec = _line_unit_vector(osm_geometry)

        candidates = self.within_buffer(line, BUFFER_M)
        diag["candidates_within_buffer"] = len(candidates)

        if not candidates:
            # Log the closest approach of the OSM way to ANY CAGIS line.
            # Sample first/middle/last OSM vertices, query nearest CAGIS
            # for each, then take the min distance from the WHOLE OSM way
            # to those candidate features (single-vertex sampling
            # over- or under-states the true closest approach on long
            # unmatched ways — flagged in Codex review of #11).
            try:
                samples_idx = {0, len(osm_geometry) // 2, len(osm_geometry) - 1}
                seen_ids: set = set()
                best_nd: float | None = None
                for si in samples_idx:
                    pt = osm_geometry[si]
                    pt_lonlat = (pt[1], pt[0])
                    nearest_rec = self.nearest(pt_lonlat)
                    if nearest_rec is None:
                        continue
                    rec_id = id(nearest_rec)
                    if rec_id in seen_ids:
                        continue
                    seen_ids.add(rec_id)
                    cagis_latlon = [
                        (lat, lon) for lon, lat in nearest_rec.geometry_lonlat
                    ]
                    nd = min(
                        _min_dist_to_polyline((p[0], p[1]), cagis_latlon)
                        for p in osm_geometry
                    )
                    if best_nd is None or nd < best_nd:
                        best_nd = nd
                if best_nd is not None:
                    diag["nearest_distance_m"] = round(best_nd, 2)
            except Exception:  # noqa: BLE001
                pass

            # Phase 2b fallback: if the closest CAGIS line is within
            # FALLBACK_BUFFER_M, try the fallback scoring path. Hits
            # land in MATCHED_FALLBACK_REVIEW (capped at REVIEW_CONFIDENCE)
            # so they populate the human-review queue without auto-promoting.
            fb = self._fallback_score(osm_geometry, osm_norm, osm_vec, line)
            if fb is not None:
                fb_conf, fb_rec, fb_name_sim, fb_haus, fb_dir = fb
                diag["confidence"] = round(fb_conf, 4)
                diag["name_similarity"] = round(fb_name_sim, 4)
                diag["hausdorff_m"] = round(fb_haus, 2)
                diag["direction_alignment"] = round(fb_dir, 4)
                diag["best_match"] = {
                    "cagis_id": fb_rec.cagis_id,
                    "cagis_name": fb_rec.name,
                }
                diag["bucket"] = BUCKET_MATCHED_FALLBACK_REVIEW
                return diag

            diag["bucket"] = BUCKET_F1_NO_CANDIDATE
            return diag

        # Score every candidate the same way match() does, but keep the
        # full scoring tuple so we can attribute the dominant penalty.
        scored: list[
            tuple[float, _CagisRecord, float, float, float, bool]
        ] = []
        for rec in candidates:
            haus = _directed_hausdorff_meters(osm_geometry, rec.geometry_lonlat)
            if haus is None:
                continue
            name_sim = _name_similarity(osm_norm, rec.name_norm)
            cagis_vec = _line_unit_vector_lonlat(rec.geometry_lonlat)
            dir_align = _direction_alignment(osm_vec, cagis_vec)
            geom_overlap = max(0.0, min(1.0, 1.0 - haus / BUFFER_M))
            confidence = (
                W_NAME * name_sim
                + W_GEOMETRY * geom_overlap
                + W_DIRECTION * dir_align
            )
            passed_haus = haus <= BUFFER_M
            scored.append(
                (confidence, rec, name_sim, haus, dir_align, passed_haus)
            )

        if not scored:
            diag["bucket"] = BUCKET_F3_GEOMETRY_FAIL
            return diag

        passing = [s for s in scored if s[5]]
        if not passing:
            # F3: candidates were close enough for the buffer query but ALL
            # had Hausdorff distance > BUFFER_M. Report the closest haus to
            # show how far over the threshold they are.
            best_over = min(scored, key=lambda s: s[3])
            diag["bucket"] = BUCKET_F3_GEOMETRY_FAIL
            diag["hausdorff_m"] = round(best_over[3], 2)
            diag["name_similarity"] = round(best_over[2], 4)
            diag["direction_alignment"] = round(best_over[4], 4)
            return diag

        # match()'s "best" is the highest-confidence Hausdorff-passing record.
        best = max(passing, key=lambda s: s[0])
        confidence, rec, name_sim, haus, dir_align, _ = best
        diag["confidence"] = round(confidence, 4)
        diag["name_similarity"] = round(name_sim, 4)
        diag["hausdorff_m"] = round(haus, 2)
        diag["direction_alignment"] = round(dir_align, 4)
        diag["best_match"] = {
            "cagis_id": rec.cagis_id,
            "cagis_name": rec.name,
        }

        if confidence >= HIGH_CONFIDENCE:
            diag["bucket"] = BUCKET_MATCHED_HIGH
            return diag
        if confidence >= REVIEW_CONFIDENCE:
            diag["bucket"] = BUCKET_MATCHED_REVIEW
            return diag

        # Confidence below REVIEW_CONFIDENCE — attribute the dominant cause.
        # F4 first: a short way whose match would have cleared review except
        # for a low direction term. Rescale by W_NON_DIRECTION so the
        # remaining (name + geometry) weights still sum to 1, and so this
        # stays correct if W_NAME / W_GEOMETRY / W_DIRECTION are retuned.
        confidence_without_dir = (
            W_NAME * name_sim
            + W_GEOMETRY * max(0.0, min(1.0, 1.0 - haus / BUFFER_M))
        )
        confidence_without_dir_rescaled = (
            confidence_without_dir / W_NON_DIRECTION
            if W_NON_DIRECTION > 0 else 0.0
        )
        if (
            way_length_m < DIAG_SHORT_WAY_M
            and dir_align < 0.5
            and confidence_without_dir_rescaled >= REVIEW_CONFIDENCE
        ):
            diag["bucket"] = BUCKET_F4_DIRECTION_DRAG
            return diag

        # F2: name is the dominant single penalty (geometry and direction
        # both look reasonable, but name_similarity is below threshold).
        geom_overlap = max(0.0, min(1.0, 1.0 - haus / BUFFER_M))
        if (
            name_sim < DIAG_NAME_FAIL_THRESHOLD
            and geom_overlap >= 0.5
            and dir_align >= 0.5
        ):
            diag["bucket"] = BUCKET_F2_NAME_FAIL
            return diag

        diag["bucket"] = BUCKET_MIXED_LOW
        return diag


def diagnose_way(osm_way: dict, index: ConflationIndex) -> dict:
    """Phase 2a entry point: per-way diagnostic dict for one OSM way.

    The return shape matches :meth:`ConflationIndex.diagnose_match` plus an
    ``id`` field for downstream aggregation. Safe to call when shapely is
    unavailable — every way ends up in F1_NO_CANDIDATE in that case.
    """
    diag = index.diagnose_match(
        osm_way.get("geometry") or [], osm_way.get("name")
    )
    out: dict[str, Any] = {"id": osm_way.get("id"), **diag}
    return out


def diagnose_all(
    all_ways: list[dict], index: ConflationIndex
) -> list[dict]:
    """Run diagnose_way over every way without mutating the input.

    Use this for Phase 2a baseline manifests — it does not write
    ``cagis_match`` (use :func:`conflate` for that). Caller is expected to
    feed the result into :func:`write_baseline_manifest`.
    """
    return [diagnose_way(w, index) for w in all_ways]


def summarize_diagnostics(rows: list[dict]) -> dict:
    """Aggregate per-way diagnostic rows into bucket counts + stats."""
    counts: dict[str, int] = {}
    f1_distances: list[float] = []
    f3_haus: list[float] = []
    f4_lengths: list[float] = []
    for r in rows:
        b = r.get("bucket", "UNKNOWN")
        counts[b] = counts.get(b, 0) + 1
        if b == BUCKET_F1_NO_CANDIDATE and r.get("nearest_distance_m") is not None:
            f1_distances.append(r["nearest_distance_m"])
        elif b == BUCKET_F3_GEOMETRY_FAIL and r.get("hausdorff_m") is not None:
            f3_haus.append(r["hausdorff_m"])
        elif b == BUCKET_F4_DIRECTION_DRAG and r.get("way_length_m") is not None:
            f4_lengths.append(r["way_length_m"])

    def _stats(values: list[float]) -> dict | None:
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        return {
            "count": n,
            "min": round(s[0], 2),
            "median": round(s[n // 2], 2),
            "max": round(s[-1], 2),
        }

    total = len(rows)
    matched_high = counts.get(BUCKET_MATCHED_HIGH, 0)
    matched_review = counts.get(BUCKET_MATCHED_REVIEW, 0)
    matched_fallback_review = counts.get(BUCKET_MATCHED_FALLBACK_REVIEW, 0)
    matched_total = matched_high + matched_review + matched_fallback_review
    return {
        "total_ways": total,
        "matched_high": matched_high,
        "matched_review": matched_review,
        "matched_fallback_review": matched_fallback_review,
        "match_rate_pct": (
            round(100.0 * matched_total / total, 2) if total else 0.0
        ),
        "auto_submit_rate_pct": (
            round(100.0 * matched_high / total, 2) if total else 0.0
        ),
        "review_queue_pct": (
            round(
                100.0 * (matched_review + matched_fallback_review) / total, 2,
            )
            if total else 0.0
        ),
        "buckets": counts,
        "f1_nearest_distance_m_stats": _stats(f1_distances),
        "f3_hausdorff_m_stats": _stats(f3_haus),
        "f4_short_way_length_m_stats": _stats(f4_lengths),
    }


def write_baseline_manifest(
    rows: list[dict],
    *,
    zone_key: str,
    git_sha: str,
    out_path: Path,
) -> dict:
    """Write a Phase 2a baseline manifest to disk and return the summary.

    The manifest stores both per-way rows (for re-aggregation later) and the
    summary stats. Filename convention: ``cagis_baseline_<gitsha>.json``.
    """
    summary = summarize_diagnostics(rows)
    payload = {
        "zone_key": zone_key,
        "git_sha": git_sha,
        "thresholds": {
            "BUFFER_M": BUFFER_M,
            "HIGH_CONFIDENCE": HIGH_CONFIDENCE,
            "REVIEW_CONFIDENCE": REVIEW_CONFIDENCE,
            "DIAG_NAME_FAIL_THRESHOLD": DIAG_NAME_FAIL_THRESHOLD,
            "DIAG_SHORT_WAY_M": DIAG_SHORT_WAY_M,
        },
        "summary": summary,
        "rows": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    log.info(
        "CAGIS Phase 2a baseline written to %s "
        "(matched %.2f%%, auto-submit %.2f%%, buckets=%s)",
        out_path,
        summary["match_rate_pct"],
        summary["auto_submit_rate_pct"],
        summary["buckets"],
    )
    return summary


def build_index(features: list[dict]) -> ConflationIndex:
    """Build a :class:`ConflationIndex` from CAGIS GeoJSON features."""
    records: list[_CagisRecord] = []
    if not SHAPELY_AVAILABLE:
        log.warning("shapely unavailable; build_index returning empty index.")
        return ConflationIndex(records)
    for feat in features:
        rec = _record_from_feature(feat)
        if rec is not None:
            records.append(rec)
    log.info("CAGIS: indexed %d / %d centerline(s)", len(records), len(features))
    return ConflationIndex(records)


def match_way(osm_way: dict, index: ConflationIndex) -> dict | None:
    """Return the best CAGIS match for one OSM way, or ``None``.

    See :meth:`ConflationIndex.match` for the schema of the returned dict.
    """
    if index is None or not index.available:
        return None
    return index.match(osm_way.get("geometry") or [], osm_way.get("name"))


def conflate(all_ways: list[dict], index: ConflationIndex) -> list[dict]:
    """Annotate every way with ``cagis_match`` (or ``None``).

    Mutates and returns ``all_ways`` so the caller can chain.
    """
    if index is None or not index.available:
        for w in all_ways:
            w.setdefault("cagis_match", None)
        return all_ways
    matched = 0
    for w in all_ways:
        m = match_way(w, index)
        w["cagis_match"] = m
        if m is not None:
            matched += 1
    log.info("CAGIS: matched %d / %d OSM ways", matched, len(all_ways))
    return all_ways


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _meters_to_degrees(geom: Any, meters: float) -> float:
    """Approximate buffer width in degrees for a geometry near its centroid.

    Wraps :func:`osm._geometry.meters_to_degrees` (kept as a shim because
    :class:`ConflationIndex` calls it with a ``geom`` argument it doesn't
    actually use, and an older test mocked the two-arg form).
    """
    del geom  # unused — geometry-independent under the WGS-84 approximation
    return _meters_to_degrees_helper(meters)


def feature_url(cagis_id: int | str) -> str:
    """Public URL for a CAGIS feature (used in UI/changeset evidence)."""
    return CAGIS_FEATURE_URL_TMPL.format(id=cagis_id)
