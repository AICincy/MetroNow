"""U.S. Census Bureau TIGER/Line 2024 county-roads conflation.

Second ground-truth source for the conflation pipeline. CAGIS (Hamilton
County) is the primary, more-current source; TIGER 2024 is a federal
fallback used where CAGIS coverage is absent or low-confidence.

Source: U.S. Census Bureau, TIGER/Line Shapefiles 2024
        https://www2.census.gov/geo/tiger/TIGER2024/ROADS/
        License: U.S. public domain (no attribution required, but credited).
        Vintage: through May 2024 (annual; frozen until TIGER 2025 ships).

This module mirrors the API surface of :mod:`osm.conflate`:
* :func:`fetch_tiger2024` — download + extract the county shapefile.
* :func:`load_tiger2024_features` — read the shapefile into the pipeline's
  ``[lat, lon]`` polyline format.
* :func:`features_in_bbox` — cheap bbox pre-filter before the STRtree.
* :func:`build_tiger_index` — STRtree over the features.
* :func:`conflate_with_tiger` — annotate every way with ``.tiger_match``.

Confidence scoring is identical to :mod:`osm.conflate`:

    0.5 * name_similarity + 0.3 * geometry_overlap + 0.2 * direction_alignment

so a TIGER score is directly comparable to a CAGIS score.

Pure-Python shapefile reader (~80 LOC). The reader supports:
* PolyLine (shape type 3) — the only type used by TIGER ROADS.
* dBASE III attribute records with C/N/F/L/D field types.

It does NOT support:
* PolyLineZ (type 13) or PolyLineM (type 23) — TIGER ROADS doesn't use them.
* dBASE memo (M) fields.
* Numeric encodings beyond ASCII / UTF-8 (TIGER labels are pure ASCII).

Coordinate reference: TIGER ships in EPSG:4269 (NAD83). For the conterminous
US — and certainly for Hamilton County — NAD83 and WGS84 differ by < 1 m at
matching scale. We treat them as equivalent for matching purposes; this is
documented as a known approximation.

Dependency note: this module needs ``shapely>=2.0``. If shapely is not
importable, :func:`build_tiger_index` returns an empty stub and the pipeline
keeps working with no TIGER evidence attached.
"""

from __future__ import annotations

import logging
import shutil
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from osm._geometry import (
    direction_alignment,
    hausdorff_meters,
    line_unit_vector,
    line_unit_vector_lonlat,
    meters_to_degrees,
    name_similarity,
)
from osm.config import CONFIG_DIR
from osm.geo import norm_name

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hamilton County, Ohio; county FIPS = 39061 (state 39 = Ohio, county 061).
TIGER_HAMILTON_FIPS = "39061"
TIGER_VINTAGE = "2024"
TIGER_BASENAME = f"tl_{TIGER_VINTAGE}_{TIGER_HAMILTON_FIPS}_roads"
TIGER_ZIP_URL = (
    f"https://www2.census.gov/geo/tiger/TIGER{TIGER_VINTAGE}/ROADS/"
    f"{TIGER_BASENAME}.zip"
)

TIGER_CACHE_DIR = CONFIG_DIR / "tiger2024_cache"

# Match thresholds — kept identical to osm.conflate so confidence scores are
# directly comparable across the two sources.
BUFFER_M = 30.0
HIGH_CONFIDENCE = 0.85
REVIEW_CONFIDENCE = 0.6

# MTFCC (MAF/TIGER Feature Class Code) → OSM highway= mapping. Per the OSM
# wiki TIGER_to_OSM_Attribute_Map page. S1400 is intentionally absent
# because it is too ambiguous to auto-suggest a reclass for (residential
# vs. unclassified depends on local context).
MTFCC_TO_OSM_HIGHWAY: dict[str, str] = {
    "S1100": "motorway",
    "S1200": "primary",
    "S1500": "unclassified",  # county roads
    "S1640": "service",       # driveway / parking-lot road
    "S1730": "service",       # alley
    "S1740": "service",
}

# MTFCC codes that we DO surface (so the UI can flag them for review) but
# never auto-suggest a reclass for, because the mapping is ambiguous.
MTFCC_AMBIGUOUS: dict[str, tuple[str, ...]] = {
    "S1400": ("residential", "unclassified"),
}

# User-Agent identifying us to census.gov as a polite, low-volume client.
TIGER_HEADERS = {
    "User-Agent": "osm-audit-pipeline/0.1 (Hamilton County TIGER audit)",
    "Accept": "application/zip",
}

# Public attribution string, surfaced in changeset metadata that cites a
# TIGER-verified fix. (Public-domain data — attribution not required, but
# included so reviewers can trace the evidence.)
TIGER_ATTRIBUTION = (
    "Source: U.S. Census Bureau, TIGER/Line Shapefiles 2024 — public domain."
)


# ---------------------------------------------------------------------------
# Optional shapely import — graceful degradation if unavailable
# ---------------------------------------------------------------------------

try:
    from shapely.geometry import LineString, Point  # type: ignore[import-not-found]
    from shapely.strtree import STRtree  # type: ignore[import-not-found]
    SHAPELY_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    log.warning(
        "shapely>=2.0 not importable (%s); TIGER conflation will be skipped.",
        exc,
    )
    LineString = None  # type: ignore[assignment,misc]
    Point = None  # type: ignore[assignment,misc]
    STRtree = None  # type: ignore[assignment,misc]
    SHAPELY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fetch + extract
# ---------------------------------------------------------------------------

def fetch_tiger2024(*, force_refresh: bool = False, timeout: int = 60) -> Path:
    """Download and extract the TIGER 2024 Hamilton County roads shapefile.

    Returns the path to the extracted .shp file. Subsequent calls reuse the
    cache; pass ``force_refresh=True`` to wipe and re-download.

    The cache lives at ``~/.config/osm/tiger2024_cache/{basename}/``. The ZIP
    is the source of truth — the .shp/.dbf/.shx/.prj are extracted next to
    it on first use.

    Raises
    ------
    requests.RequestException
        If the download fails. Callers may catch and degrade gracefully.
    FileNotFoundError
        If the ZIP downloaded successfully but did not contain the expected
        .shp member (defensive — has not been observed in practice).
    """
    extract_dir = TIGER_CACHE_DIR / TIGER_BASENAME
    shp_path = extract_dir / f"{TIGER_BASENAME}.shp"
    zip_path = extract_dir / f"{TIGER_BASENAME}.zip"

    if force_refresh and extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)

    if shp_path.exists():
        log.debug("TIGER: using cached shapefile %s", shp_path)
        return shp_path

    extract_dir.mkdir(parents=True, exist_ok=True)
    log.info("TIGER: downloading %s", TIGER_ZIP_URL)
    resp = requests.get(
        TIGER_ZIP_URL,
        headers=TIGER_HEADERS,
        timeout=timeout,
        stream=True,
    )
    resp.raise_for_status()

    with zip_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                fh.write(chunk)
    log.info("TIGER: downloaded %d bytes to %s",
             zip_path.stat().st_size, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    if not shp_path.exists():
        raise FileNotFoundError(
            f"Expected {shp_path} after extracting {zip_path}; "
            f"archive contained: {sorted(p.name for p in extract_dir.iterdir())}"
        )
    return shp_path


# ---------------------------------------------------------------------------
# Pure-Python shapefile reader
#
# Implements the subset of the Esri shapefile / dBASE III format that TIGER
# ROADS uses. Documented limitations:
#   * Shape type 3 (PolyLine) only — no Z/M variants (13/23).
#   * dBASE III field types C, N, F, D, L (no memo M, no binary B).
#   * Coordinates returned as ``[lat, lon]`` to match the rest of the
#     pipeline (callers don't need to know about lon/lat ordering).
# ---------------------------------------------------------------------------

def _read_shapefile_polylines(shp_path: Path) -> list[list[list[float]]]:
    """Return a list of polylines — each polyline is a list of ``[lat, lon]``
    vertices. Only PolyLine (shape type 3) records are supported.

    The longest part of a multi-part record is returned (multi-part PolyLine
    records are rare in TIGER ROADS — they're used for divided highways
    sharing one record — and our matcher is happiest with one ring per
    record, identical to the choice made in :mod:`osm.conflate`).
    """
    out: list[list[list[float]]] = []
    with shp_path.open("rb") as fh:
        header = fh.read(100)
        if len(header) < 100:
            raise ValueError(f"Shapefile {shp_path} truncated header")
        magic = struct.unpack(">i", header[0:4])[0]
        if magic != 9994:
            raise ValueError(f"Shapefile {shp_path} bad magic {magic}")
        # Shape type at byte 32 (LE int32). 3 = PolyLine.
        file_shape_type = struct.unpack("<i", header[32:36])[0]
        if file_shape_type != 3:
            log.warning("TIGER: unexpected shapefile type %d (expected 3)",
                        file_shape_type)
        while True:
            rec_header = fh.read(8)
            if len(rec_header) < 8:
                break  # EOF
            # rec_num is BE int32 (unused), content_len BE int32 in 16-bit words.
            _rec_num, content_len_words = struct.unpack(">ii", rec_header)
            content = fh.read(content_len_words * 2)
            if len(content) < 4:
                break
            shape_type = struct.unpack("<i", content[0:4])[0]
            if shape_type == 0:
                # Null shape — skip but keep parsing.
                continue
            if shape_type != 3:
                # Non-PolyLine record. Skip without complaining too loudly;
                # TIGER ROADS shouldn't contain these but we want to be
                # defensive.
                log.debug("TIGER: skipping shape type %d", shape_type)
                continue
            # PolyLine layout:
            #   [0:4]   shape_type (already read)
            #   [4:36]  bbox (4 doubles LE)
            #   [36:40] num_parts int32 LE
            #   [40:44] num_points int32 LE
            #   [44:44+4*num_parts] parts indices
            #   then num_points (X, Y) doubles
            num_parts, num_points = struct.unpack("<ii", content[36:44])
            if num_parts <= 0 or num_points <= 0:
                continue
            parts_end = 44 + 4 * num_parts
            parts = list(
                struct.unpack(f"<{num_parts}i", content[44:parts_end])
            )
            points_blob = content[parts_end : parts_end + 16 * num_points]
            # Iterate parts so we can pick the longest one (mirrors
            # osm.conflate._record_from_feature).
            best_part: list[list[float]] | None = None
            for i, start_idx in enumerate(parts):
                end_idx = parts[i + 1] if i + 1 < num_parts else num_points
                seg_pts: list[list[float]] = []
                for k in range(start_idx, end_idx):
                    off = k * 16
                    x, y = struct.unpack(
                        "<dd", points_blob[off : off + 16]
                    )
                    # x = longitude, y = latitude in NAD83 → returned as
                    # [lat, lon] to match the rest of the pipeline.
                    seg_pts.append([y, x])
                if best_part is None or len(seg_pts) > len(best_part):
                    best_part = seg_pts
            if best_part is not None and len(best_part) >= 2:
                out.append(best_part)
    return out


def _read_dbf_records(dbf_path: Path) -> list[dict[str, Any]]:
    """Read a dBASE III .dbf into a list of plain dicts.

    Supports the field types used by TIGER attribute tables: C (text),
    N (numeric), F (float), L (logical), D (date — returned as a string).
    Memo (M) and binary (B) fields are returned as ``None`` because TIGER
    ROADS doesn't use them.
    """
    out: list[dict[str, Any]] = []
    with dbf_path.open("rb") as fh:
        header = fh.read(32)
        if len(header) < 32:
            raise ValueError(f"DBF {dbf_path} truncated header")
        num_records, header_len, record_len = struct.unpack(
            "<IHH", header[4:12]
        )
        # Field descriptors: 32 bytes each, terminator 0x0D one byte before
        # the record area starts. Read all-at-once so we don't depend on
        # ``BufferedReader.peek`` (the binary file we get is buffered, but
        # explicit is better).
        descriptors_blob = fh.read(header_len - 32)
        fields: list[tuple[str, str, int]] = []
        i = 0
        while i + 32 <= len(descriptors_blob):
            chunk = descriptors_blob[i : i + 32]
            if chunk[0:1] == b"\x0d":
                break
            raw_name = chunk[0:11]
            name = raw_name.split(b"\x00", 1)[0].decode(
                "ascii", errors="replace"
            )
            ftype = chunk[11:12].decode("ascii", errors="replace")
            flen = chunk[16]
            fields.append((name, ftype, flen))
            i += 32
        # Make sure we're positioned at the start of the record area regardless
        # of how the descriptor block was sized.
        fh.seek(header_len)
        for _ in range(num_records):
            rec = fh.read(record_len)
            if len(rec) < record_len:
                break
            if rec[0:1] == b"*":
                # Deleted record marker — skip.
                continue
            row: dict[str, Any] = {}
            offset = 1  # skip 1-byte deletion marker
            for name, ftype, flen in fields:
                raw = rec[offset : offset + flen]
                offset += flen
                row[name] = _parse_dbf_value(raw, ftype)
            out.append(row)
    return out


def _parse_dbf_value(raw: bytes, ftype: str) -> Any:
    """Convert a raw dBASE III field to a Python value."""
    text = raw.decode("ascii", errors="replace").strip()
    if ftype == "C":
        return text or None
    if ftype in ("N", "F"):
        if not text:
            return None
        try:
            if "." in text:
                return float(text)
            return int(text)
        except ValueError:
            return None
    if ftype == "L":
        if text.upper() in ("Y", "T"):
            return True
        if text.upper() in ("N", "F"):
            return False
        return None
    if ftype == "D":
        return text or None
    return None


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_tiger2024_features(
    *,
    shp_path: Path | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """Load TIGER 2024 county roads as a list of pipeline-shaped features.

    Returns features in the same shape :mod:`osm.conflate` consumes:

        {"geometry": [[lat, lon], ...],
         "properties": {"LINEARID": ..., "FULLNAME": ..., "MTFCC": ...,
                        "RTTYP": ...}}

    If ``shp_path`` is None, downloads / extracts via :func:`fetch_tiger2024`
    (cached). Pass an explicit path in tests.

    Returns an empty list and logs at WARNING if the shapefile can't be
    fetched or parsed — pipeline stays usable.
    """
    try:
        if shp_path is None:
            shp_path = fetch_tiger2024(force_refresh=force_refresh)
    except Exception as exc:  # noqa: BLE001
        log.warning("TIGER: could not fetch shapefile (%s); returning empty.",
                    exc)
        return []

    dbf_path = shp_path.with_suffix(".dbf")
    try:
        polylines = _read_shapefile_polylines(shp_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("TIGER: could not parse %s (%s); returning empty.",
                    shp_path, exc)
        return []
    try:
        attrs = _read_dbf_records(dbf_path) if dbf_path.exists() else []
    except Exception as exc:  # noqa: BLE001
        log.warning("TIGER: could not parse %s (%s); features get no props.",
                    dbf_path, exc)
        attrs = []

    out: list[dict] = []
    for i, geom in enumerate(polylines):
        props = attrs[i] if i < len(attrs) else {}
        out.append({"geometry": geom, "properties": props})
    log.info("TIGER: loaded %d feature(s) from %s", len(out), shp_path.name)
    return out


# ---------------------------------------------------------------------------
# Bbox pre-filter
# ---------------------------------------------------------------------------

def features_in_bbox(
    features: list[dict],
    bbox: tuple[float, float, float, float],
) -> list[dict]:
    """Return features whose bbox intersects the given (south, west, north,
    east) zone bbox.

    Cheap O(N) filter — TIGER 2024 Hamilton County has ~30k features and a
    full STRtree query is fast, but this filter shaves the work for callers
    that scan multiple zones from one shapefile.
    """
    south, west, north, east = bbox
    out: list[dict] = []
    for feat in features:
        geom = feat.get("geometry") or []
        if not geom:
            continue
        # Compute feature bbox.
        flats = [p[0] for p in geom]
        flons = [p[1] for p in geom]
        f_south, f_north = min(flats), max(flats)
        f_west, f_east = min(flons), max(flons)
        # Standard bbox intersection.
        if f_east < west or f_west > east:
            continue
        if f_north < south or f_south > north:
            continue
        out.append(feat)
    return out


# ---------------------------------------------------------------------------
# Index + match
# ---------------------------------------------------------------------------

@dataclass
class _TigerRecord:
    """One indexed TIGER feature ready for matching."""
    tiger_id: str | None       # LINEARID
    tiger_name: str | None     # FULLNAME
    name_norm: str | None
    mtfcc: str | None
    rttyp: str | None
    geometry_lonlat: list[tuple[float, float]]
    line: Any  # shapely LineString
    raw_props: dict


def _record_from_feature(feat: dict) -> _TigerRecord | None:
    """Build a :class:`_TigerRecord` from a pipeline-shaped TIGER feature."""
    if not SHAPELY_AVAILABLE:
        return None
    geom_latlon = feat.get("geometry") or []
    if len(geom_latlon) < 2:
        return None
    # Convert [lat, lon] → [(lon, lat)] for shapely + Hausdorff helpers.
    lonlat: list[tuple[float, float]] = [
        (float(p[1]), float(p[0])) for p in geom_latlon
    ]
    try:
        line = LineString(lonlat)
    except Exception as exc:  # noqa: BLE001
        log.debug("TIGER feature has invalid geometry: %s", exc)
        return None
    props = feat.get("properties") or {}
    name = props.get("FULLNAME")
    return _TigerRecord(
        tiger_id=props.get("LINEARID"),
        tiger_name=name,
        name_norm=norm_name(name),
        mtfcc=props.get("MTFCC"),
        rttyp=props.get("RTTYP"),
        geometry_lonlat=lonlat,
        line=line,
        raw_props=props,
    )


class TigerIndex:
    """Spatial index over TIGER features, parallel to :class:`ConflationIndex`.

    When shapely is unavailable, every method returns empty/None so the
    pipeline keeps running with no TIGER evidence attached.
    """

    def __init__(self, records: list[_TigerRecord]):
        self.records = records
        self._tree = None
        self._line_records: list[_TigerRecord] = []
        if SHAPELY_AVAILABLE and records:
            geoms = [r.line for r in records]
            self._line_records = list(records)
            try:
                self._tree = STRtree(geoms)
            except Exception as exc:  # noqa: BLE001
                log.warning("TIGER: could not build STRtree: %s", exc)
                self._tree = None

    def __len__(self) -> int:
        return len(self.records)

    @property
    def available(self) -> bool:
        return SHAPELY_AVAILABLE and self._tree is not None

    def _candidates(self, geom: Any, buffer_deg: float) -> list[_TigerRecord]:
        if self._tree is None:
            return []
        try:
            idx_array = self._tree.query(geom.buffer(buffer_deg))
        except Exception as exc:  # noqa: BLE001
            log.debug("TIGER: STRtree query failed: %s", exc)
            return []
        out: list[_TigerRecord] = []
        for raw in idx_array:
            i = int(raw)
            if 0 <= i < len(self._line_records):
                out.append(self._line_records[i])
        return out

    def within_buffer(self, line: Any, meters: float) -> list[_TigerRecord]:
        if self._tree is None:
            return []
        return self._candidates(line, meters_to_degrees(meters))

    def nearest(
        self, point_lonlat: tuple[float, float],
    ) -> _TigerRecord | None:
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
        self, osm_geometry: list[list[float]], osm_name: str | None,
    ) -> dict | None:
        """Return the best TIGER match for an OSM way, or ``None``.

        Match dict shape (parallel to CAGIS):

            {"tiger_id": LINEARID, "tiger_name": FULLNAME,
             "tiger_mtfcc": MTFCC, "tiger_rttyp": RTTYP,
             "confidence": float, "name_similarity": float,
             "hausdorff_m": float, "name_match": bool}
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
        osm_vec = line_unit_vector(osm_geometry)

        best: tuple[float, _TigerRecord, float, float] | None = None
        for rec in candidates:
            haus = hausdorff_meters(osm_geometry, rec.geometry_lonlat)
            if haus is None or haus > BUFFER_M:
                continue
            sim = name_similarity(osm_norm, rec.name_norm)
            tiger_vec = line_unit_vector_lonlat(rec.geometry_lonlat)
            dir_align = direction_alignment(osm_vec, tiger_vec)
            geom_overlap = max(0.0, min(1.0, 1.0 - haus / BUFFER_M))
            confidence = (
                0.5 * sim
                + 0.3 * geom_overlap
                + 0.2 * dir_align
            )
            if best is None or confidence > best[0]:
                best = (confidence, rec, sim, haus)

        if best is None:
            return None
        confidence, rec, name_sim, haus = best
        return {
            "tiger_id": rec.tiger_id,
            "tiger_name": rec.tiger_name,
            "tiger_mtfcc": rec.mtfcc,
            "tiger_rttyp": rec.rttyp,
            "confidence": round(confidence, 4),
            "name_similarity": round(name_sim, 4),
            "hausdorff_m": round(haus, 2),
            "name_match": bool(
                osm_norm is not None
                and rec.name_norm is not None
                and name_sim >= 0.85
            ),
        }


def build_tiger_index(features: list[dict]) -> TigerIndex:
    """Build a :class:`TigerIndex` from pipeline-shaped TIGER features."""
    records: list[_TigerRecord] = []
    if not SHAPELY_AVAILABLE:
        log.warning("shapely unavailable; build_tiger_index returns empty.")
        return TigerIndex(records)
    for feat in features:
        rec = _record_from_feature(feat)
        if rec is not None:
            records.append(rec)
    log.info("TIGER: indexed %d / %d feature(s)", len(records), len(features))
    return TigerIndex(records)


def match_way(osm_way: dict, index: TigerIndex) -> dict | None:
    """Return the best TIGER match for one OSM way, or ``None``."""
    if index is None or not index.available:
        return None
    return index.match(osm_way.get("geometry") or [], osm_way.get("name"))


def conflate_with_tiger(
    all_ways: list[dict], index: TigerIndex,
) -> list[dict]:
    """Annotate every way with ``tiger_match`` (or ``None``).

    Mutates and returns ``all_ways``.
    """
    if index is None or not index.available:
        for w in all_ways:
            w.setdefault("tiger_match", None)
        return all_ways
    matched = 0
    for w in all_ways:
        m = match_way(w, index)
        w["tiger_match"] = m
        if m is not None:
            matched += 1
    log.info("TIGER: matched %d / %d OSM ways", matched, len(all_ways))
    return all_ways


# ---------------------------------------------------------------------------
# Public helpers used by review.py
# ---------------------------------------------------------------------------

def suggested_highway_for_mtfcc(mtfcc: str | None) -> str | None:
    """Return the OSM highway= value implied by an MTFCC, or ``None`` if the
    code is missing or ambiguous."""
    if not mtfcc:
        return None
    return MTFCC_TO_OSM_HIGHWAY.get(mtfcc)


def is_ambiguous_mtfcc(mtfcc: str | None) -> bool:
    """True if ``mtfcc`` is one we surface for review but never auto-suggest."""
    return bool(mtfcc) and mtfcc in MTFCC_AMBIGUOUS
