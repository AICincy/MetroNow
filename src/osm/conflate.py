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

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

from osm.config import CONFIG_DIR
from osm.geo import haversine_m, norm_name
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
    """Stable short hash for cache filenames keyed by bbox."""
    payload = ",".join(f"{v:.6f}" for v in bbox)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _cache_path(bbox: tuple[float, float, float, float]) -> Path:
    return CAGIS_CACHE_DIR / f"centerlines-{_bbox_hash(bbox)}.geojson"


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CAGIS_CACHE_TTL_DAYS * 86_400


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

        candidates = self.within_buffer(line, BUFFER_M)
        if not candidates:
            return None

        osm_norm = norm_name(osm_name)
        osm_vec = _line_unit_vector(osm_geometry)

        best: tuple[float, _CagisRecord, float, float, float] | None = None
        for rec in candidates:
            haus = _hausdorff_meters(osm_geometry, rec.geometry_lonlat)
            if haus is None or haus > BUFFER_M:
                # Even with bbox proximity, geometry may be too far.
                continue
            name_sim = _name_similarity(osm_norm, rec.name_norm)
            cagis_vec = _line_unit_vector_lonlat(rec.geometry_lonlat)
            dir_align = _direction_alignment(osm_vec, cagis_vec)
            geom_overlap = max(0.0, min(1.0, 1.0 - haus / BUFFER_M))
            confidence = (
                0.5 * name_sim
                + 0.3 * geom_overlap
                + 0.2 * dir_align
            )
            if best is None or confidence > best[0]:
                best = (confidence, rec, name_sim, haus, dir_align)

        if best is None:
            return None
        confidence, rec, name_sim, haus, _dir = best
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
        }


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

    1 deg latitude ≈ 111_320 m; we use that as a conservative bound (longitude
    degrees are smaller at Hamilton County's latitude, which makes the buffer
    *bigger* in practice — fine for candidate selection).
    """
    return meters / 111_000.0


# CAGIS uses abbreviated street suffixes/prefixes; OSM uses spelled-out
# forms. Without expanding both sides, similarity scores get artificially
# low. The map is intentionally minimal — extend as we see new shorthand.
_CAGIS_EXPANSIONS = {
    " av ": " avenue ",
    " blvd ": " boulevard ",
    " cir ": " circle ",
    " ct ": " court ",
    " dr ": " drive ",
    " expy ": " expressway ",
    " exwy ": " expressway ",
    " fwy ": " freeway ",
    " hwy ": " highway ",
    " ln ": " lane ",
    " pkwy ": " parkway ",
    " pl ": " place ",
    " rd ": " road ",
    " sq ": " square ",
    " st ": " street ",
    " ter ": " terrace ",
    " trl ": " trail ",
    " way ": " way ",
    " e ": " east ",
    " w ": " west ",
    " n ": " north ",
    " s ": " south ",
    " ne ": " northeast ",
    " nw ": " northwest ",
    " se ": " southeast ",
    " sw ": " southwest ",
}


def _expand_abbrev(s: str) -> str:
    """Expand common CAGIS abbreviations so name-similarity matches OSM
    spelled-out forms ("OAK ST" ↔ "Oak Street").
    """
    padded = " " + s + " "
    # Run multiple passes so consecutive tokens (e.g. "E OAK ST") expand.
    for _ in range(2):
        for short, long_ in _CAGIS_EXPANSIONS.items():
            padded = padded.replace(short, long_)
    return padded.strip()


def _name_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    expanded_a = _expand_abbrev(a)
    expanded_b = _expand_abbrev(b)
    if expanded_a == expanded_b:
        return 1.0
    return SequenceMatcher(None, expanded_a, expanded_b).ratio()


def _line_unit_vector(geom_latlon: list[list[float]]) -> tuple[float, float] | None:
    if len(geom_latlon) < 2:
        return None
    lat1, lon1 = geom_latlon[0][0], geom_latlon[0][1]
    lat2, lon2 = geom_latlon[-1][0], geom_latlon[-1][1]
    dx = lon2 - lon1
    dy = lat2 - lat1
    mag = math.hypot(dx, dy)
    if mag == 0:
        return None
    return (dx / mag, dy / mag)


def _line_unit_vector_lonlat(
    geom_lonlat: list[tuple[float, float]]
) -> tuple[float, float] | None:
    if len(geom_lonlat) < 2:
        return None
    lon1, lat1 = geom_lonlat[0]
    lon2, lat2 = geom_lonlat[-1]
    dx = lon2 - lon1
    dy = lat2 - lat1
    mag = math.hypot(dx, dy)
    if mag == 0:
        return None
    return (dx / mag, dy / mag)


def _direction_alignment(
    a: tuple[float, float] | None, b: tuple[float, float] | None
) -> float:
    """0..1 alignment score (parallel = 1, perpendicular/anti-parallel ≤ 0).

    Streets are *un*directed in geometry — the user-facing oneway flag is
    handled separately — so we use ``abs(cos)`` to treat A→B and B→A as
    equally aligned.
    """
    if a is None or b is None:
        return 0.0
    dot = a[0] * b[0] + a[1] * b[1]
    return max(0.0, min(1.0, abs(dot)))


def _hausdorff_meters(
    osm_latlon: list[list[float]],
    cagis_lonlat: list[tuple[float, float]],
) -> float | None:
    """Symmetric Hausdorff distance in metres.

    "Every point of A is within X metres of B" implies same physical line.
    We measure point-to-segment (true perpendicular projection), not
    point-to-vertex, so two polylines representing the same street with
    different vertex break-points still score near-zero Hausdorff.
    """
    if not osm_latlon or not cagis_lonlat:
        return None
    osm_pts = [(p[0], p[1]) for p in osm_latlon]  # (lat, lon)
    cag_pts = [(lat, lon) for lon, lat in cagis_lonlat]
    d1 = max(_min_dist_to_polyline(p, cag_pts) for p in osm_pts)
    d2 = max(_min_dist_to_polyline(p, osm_pts) for p in cag_pts)
    return max(d1, d2)


def _point_segment_dist_m(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """Approximate distance from point P to segment A-B in metres.

    Project P onto AB in flat ENU-ish coordinates (fine for ≪ 1 km segments
    near Hamilton County's latitude), then take the haversine of the foot.
    """
    # Flat-earth deltas in metres.
    lat_m = 111_320.0
    lon_m = 111_320.0 * math.cos(math.radians((a_lat + b_lat) / 2.0))
    ax = (a_lon - p_lon) * lon_m
    ay = (a_lat - p_lat) * lat_m
    bx = (b_lon - p_lon) * lon_m
    by = (b_lat - p_lat) * lat_m
    dx = bx - ax
    dy = by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        # Degenerate segment — fall back to vertex distance.
        return haversine_m(p_lat, p_lon, a_lat, a_lon)
    # t = ((P - A) · (B - A)) / |B - A|^2
    # In our P-shifted frame, P is at origin, so (P - A) = -A.
    t = (-ax * dx + -ay * dy) / seg_len2
    t = max(0.0, min(1.0, t))
    fx = ax + t * dx
    fy = ay + t * dy
    return math.hypot(fx, fy)


def _min_dist_to_polyline(
    point_latlon: tuple[float, float],
    polyline_latlon: list[tuple[float, float]],
) -> float:
    """Min distance from a point to any segment of the polyline (metres)."""
    if not polyline_latlon:
        return float("inf")
    if len(polyline_latlon) == 1:
        lat, lon = polyline_latlon[0]
        return haversine_m(point_latlon[0], point_latlon[1], lat, lon)
    p_lat, p_lon = point_latlon
    best = float("inf")
    for i in range(len(polyline_latlon) - 1):
        a_lat, a_lon = polyline_latlon[i]
        b_lat, b_lon = polyline_latlon[i + 1]
        d = _point_segment_dist_m(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon)
        if d < best:
            best = d
    return best


def feature_url(cagis_id: int | str) -> str:
    """Public URL for a CAGIS feature (used in UI/changeset evidence)."""
    return CAGIS_FEATURE_URL_TMPL.format(id=cagis_id)
