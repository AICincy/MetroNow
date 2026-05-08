"""Zone polygon loading and containment.

Phase 4a stage 1 introduces a polygon clip step between the bbox-bound
Overpass harvest and the rest of the pipeline. Bboxes overshoot the
real spatial extent of CAGIS coverage — Forest Park's bbox bleeds into
Butler County (CAGIS coverage ends at the Hamilton County line),
producing 78% F1 (no-CAGIS-candidate) on its harvested ways. Clipping
to Hamilton County removes that bleed without touching the Overpass
query itself.

Containment is centroid-based (cheap, deterministic, sufficient for
"do we keep this way for analysis?"). Ways straddling the county line
are kept iff their centroid sits inside.

Future stages (4a stage 2): per-zone municipal polygons sourced from
CAGIS jurisdiction layers will replace the single county clip with
zone-specific polygons matching MetroNow's actual operational area.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ZONES_DIR = Path(__file__).parent / "zones"
HAMILTON_COUNTY_GEOJSON = ZONES_DIR / "hamilton-county.geojson"

# Phase 4a stage 2: per-zone polygons live next to the county polygon
# under src/osm/zones/, keyed by zone_key. Each is a 500m-buffered union
# of the constituent municipalities (cities + CDPs filtered to Hamilton
# County), sourced from Census TIGERweb Places. See the source GeoJSON
# files for provenance.
def _zone_geojson(zone_key: str) -> Path:
    return ZONES_DIR / f"{zone_key}.geojson"


# ---------------------------------------------------------------------------
# Optional shapely import — same pattern as conflate.py. Without shapely
# the clip becomes a no-op and the rest of the pipeline keeps working.
# ---------------------------------------------------------------------------

try:
    from shapely.geometry import (  # type: ignore[import-not-found]
        MultiPolygon,
        Point,
        Polygon,
        shape,
    )
    SHAPELY_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    log.warning(
        "shapely>=2.0 not importable (%s); polygon clipping will be skipped.",
        exc,
    )
    Point = None  # type: ignore[assignment,misc]
    Polygon = None  # type: ignore[assignment,misc]
    MultiPolygon = None  # type: ignore[assignment,misc]
    shape = None  # type: ignore[assignment]
    SHAPELY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

_POLYGON_CACHE: dict[str, Any] = {}


def _load_polygon_from(path: Path) -> Any:
    """Read a single-feature GeoJSON polygon file. Returns None on any error."""
    if not SHAPELY_AVAILABLE:
        return None
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            feat = json.load(fh)
        return shape(feat["geometry"])
    except (OSError, KeyError, ValueError) as exc:
        log.error("Could not parse polygon at %s: %s", path, exc)
        return None


def load_hamilton_county_polygon() -> Any:
    """Return the bundled Hamilton County polygon as a shapely geometry.

    Returns ``None`` when shapely is unavailable. Memoised after first call.
    """
    cached = _POLYGON_CACHE.get("__county__")
    if cached is not None:
        return cached
    geom = _load_polygon_from(HAMILTON_COUNTY_GEOJSON)
    if geom is None and SHAPELY_AVAILABLE:
        log.warning(
            "Hamilton County polygon missing at %s; clip will be a no-op.",
            HAMILTON_COUNTY_GEOJSON,
        )
    if geom is not None:
        _POLYGON_CACHE["__county__"] = geom
    return geom


def load_zone_polygon(
    zone_key: str, *, county_fallback_only: bool = False,
) -> Any:
    """Return the clip polygon for ``zone_key``.

    Default (Phase 4a stage 3): returns the authoritative MetroNow
    operational polygon for ``zone_key`` — sourced from SORTA's
    published web map (ArcGIS Web Map item ba2063d68a3e41bd86d486d372991d65,
    "MetroNow!" by metro_mlinder, linked from go-metro.com/riding-metro/metronow/),
    200 m buffered for first-mile/last-mile walking edges, clipped at
    the Hamilton County boundary. See the per-zone GeoJSON files'
    properties for full provenance.

    With ``county_fallback_only=True``: returns the Hamilton County
    polygon directly. Use when downstream code needs the same broad
    clip across all zones (e.g., a pre-zone-specific scan).

    Falls back to the county polygon if the per-zone GeoJSON is missing
    (defensive — should never happen on a clean checkout).
    """
    if not county_fallback_only:
        cache_key = f"zone:{zone_key}"
        cached = _POLYGON_CACHE.get(cache_key)
        if cached is not None:
            return cached
        zone_geom = _load_polygon_from(_zone_geojson(zone_key))
        if zone_geom is not None:
            _POLYGON_CACHE[cache_key] = zone_geom
            return zone_geom
    return load_hamilton_county_polygon()


# ---------------------------------------------------------------------------
# Containment + clip
# ---------------------------------------------------------------------------

def _element_centroid(element: dict) -> tuple[float, float] | None:
    """Best-effort (lat, lon) centroid for an Overpass element.

    Ways: midpoint of the geometry array. Nodes: own (lat, lon).
    Relations: skip (we don't try to centroid a turn restriction).
    Returns ``None`` when no meaningful centroid is available.
    """
    etype = element.get("type")
    if etype == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return (float(lat), float(lon))
        return None
    if etype == "way":
        geom = element.get("geometry") or []
        if not geom:
            return None
        # Overpass `out meta geom` gives [{'lat':..., 'lon':...}, ...].
        try:
            mid = geom[len(geom) // 2]
            lat = mid.get("lat") if isinstance(mid, dict) else mid[0]
            lon = mid.get("lon") if isinstance(mid, dict) else mid[1]
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return (float(lat), float(lon))
        except (TypeError, IndexError, KeyError):
            return None
    return None


def point_in_polygon(lat: float, lon: float, polygon: Any) -> bool:
    """True if ``(lat, lon)`` lies within ``polygon``. False on bad input."""
    if polygon is None or not SHAPELY_AVAILABLE:
        # No polygon → caller should not have called us; treat as "keep".
        return True
    try:
        # Shapely geometries are (x, y) = (lon, lat).
        return polygon.contains(Point(lon, lat))
    except Exception:  # noqa: BLE001
        return True


def clip_elements_to_polygon(
    elements: list[dict], polygon: Any
) -> tuple[list[dict], dict]:
    """Drop way / node elements whose centroid is outside ``polygon``.

    Keeps relations as-is (we can't cheaply centroid a turn restriction
    without resolving its members; Overpass already trims to bbox so
    the bleed is small).

    Returns ``(kept_elements, stats)`` where ``stats`` records the
    counts dropped per element type for the diagnostic logs.
    """
    if polygon is None or not SHAPELY_AVAILABLE:
        return elements, {"clipped": False, "reason": "polygon-unavailable"}

    kept: list[dict] = []
    dropped = {"way": 0, "node": 0}
    no_centroid = 0
    for el in elements:
        etype = el.get("type")
        if etype == "relation":
            kept.append(el)
            continue
        centroid = _element_centroid(el)
        if centroid is None:
            kept.append(el)
            no_centroid += 1
            continue
        lat, lon = centroid
        if point_in_polygon(lat, lon, polygon):
            kept.append(el)
        else:
            key = etype if isinstance(etype, str) and etype in dropped else "way"
            dropped[key] = dropped.get(key, 0) + 1
    stats = {
        "clipped": True,
        "kept": len(kept),
        "dropped_total": sum(dropped.values()),
        "dropped_by_type": dropped,
        "no_centroid": no_centroid,
        "in": len(elements),
    }
    return kept, stats
