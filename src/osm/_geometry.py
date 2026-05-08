"""Shared geometry helpers used by conflation against multiple ground-truth
sources (CAGIS, TIGER/Line 2024).

These helpers live in their own module to keep the source-specific
``conflate`` modules thin and to avoid the duplication that would otherwise
appear once we have more than one ground-truth source.

All helpers are pure-Python and have no shapely dependency — shapely is only
used for the spatial index (``STRtree``) inside the per-source modules. That
split makes it easy to keep the metric calculations testable in isolation
even on environments where shapely is missing.

Conventions:
* OSM geometry comes in as ``[[lat, lon], ...]`` (the in-pipeline format used
  throughout :mod:`osm.classify` and :mod:`osm.fetch`).
* Source geometry (CAGIS GeoJSON, TIGER shapefile) is ``[(lon, lat), ...]``
  because that is the GeoJSON / Esri ordering.

The metric we compute matches what :mod:`osm.conflate` shipped with so the
existing CAGIS confidence scores keep their meaning byte-for-byte.
"""

from __future__ import annotations

import math
from difflib import SequenceMatcher

from osm.geo import haversine_m

__all__ = [
    "expand_abbrev",
    "name_similarity",
    "line_unit_vector",
    "line_unit_vector_lonlat",
    "direction_alignment",
    "hausdorff_meters",
    "min_dist_to_polyline",
    "point_segment_dist_m",
    "meters_to_degrees",
    "polyline_length_m",
]


# ---------------------------------------------------------------------------
# Name normalisation — both CAGIS and TIGER use postal-style abbreviations
# (e.g. "OAK ST", "MAIN AVE") whereas OSM convention spells them out
# ("Oak Street", "Main Avenue"). Without expanding both sides, similarity
# scores would tank for matches that are correct in reality.
# ---------------------------------------------------------------------------

_ABBREVIATIONS = {
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


def expand_abbrev(s: str) -> str:
    """Expand common postal-style abbreviations to spelled-out forms.

    Used to align CAGIS / TIGER label conventions with OSM's spelled-out
    convention. Two passes catch consecutive tokens like "E OAK ST".
    """
    padded = " " + s + " "
    for _ in range(2):
        for short, long_ in _ABBREVIATIONS.items():
            padded = padded.replace(short, long_)
    return padded.strip()


def name_similarity(a: str | None, b: str | None) -> float:
    """Ratcliff-Obershelp similarity (0..1) with abbreviation expansion."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    expanded_a = expand_abbrev(a)
    expanded_b = expand_abbrev(b)
    if expanded_a == expanded_b:
        return 1.0
    return SequenceMatcher(None, expanded_a, expanded_b).ratio()


# ---------------------------------------------------------------------------
# Direction vectors — used to weight matches where geometry overlaps but
# the polylines run perpendicular (rare but real, near 4-way intersections
# where two streets share endpoints).
# ---------------------------------------------------------------------------

def line_unit_vector(geom_latlon: list[list[float]]) -> tuple[float, float] | None:
    """Unit vector from first to last vertex of a [lat, lon] polyline.

    Returns ``None`` for empty / degenerate input.
    """
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


def line_unit_vector_lonlat(
    geom_lonlat: list[tuple[float, float]],
) -> tuple[float, float] | None:
    """Unit vector from first to last vertex of a [(lon, lat), ...] polyline."""
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


def direction_alignment(
    a: tuple[float, float] | None, b: tuple[float, float] | None,
) -> float:
    """0..1 alignment score (1 = parallel, 0 = perpendicular).

    Streets are *un*directed in geometry — the user-facing oneway flag is
    handled separately — so we use ``abs(cos)`` to treat A→B and B→A as
    equally aligned.
    """
    if a is None or b is None:
        return 0.0
    dot = a[0] * b[0] + a[1] * b[1]
    return max(0.0, min(1.0, abs(dot)))


# ---------------------------------------------------------------------------
# Hausdorff distance in metres — point-to-segment, projecting in flat ENU
# coords near the centroid latitude. Fine for ≪1 km segments at Hamilton
# County's latitude (~39.2°N).
# ---------------------------------------------------------------------------

def point_segment_dist_m(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """Approximate distance from point P to segment A-B in metres."""
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
        return haversine_m(p_lat, p_lon, a_lat, a_lon)
    # P is at origin in P-shifted frame, so (P - A) = -A.
    t = (-ax * dx + -ay * dy) / seg_len2
    t = max(0.0, min(1.0, t))
    fx = ax + t * dx
    fy = ay + t * dy
    return math.hypot(fx, fy)


def min_dist_to_polyline(
    point_latlon: tuple[float, float],
    polyline_latlon: list[tuple[float, float]],
) -> float:
    """Minimum distance from a point to any segment of the polyline (m)."""
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
        d = point_segment_dist_m(p_lat, p_lon, a_lat, a_lon, b_lat, b_lon)
        if d < best:
            best = d
    return best


def hausdorff_meters(
    osm_latlon: list[list[float]],
    src_lonlat: list[tuple[float, float]],
) -> float | None:
    """Symmetric Hausdorff distance in metres between OSM and source polylines.

    OSM is ``[[lat, lon], ...]``; source is ``[(lon, lat), ...]`` (the GeoJSON
    convention used by both CAGIS and TIGER).
    """
    if not osm_latlon or not src_lonlat:
        return None
    osm_pts = [(p[0], p[1]) for p in osm_latlon]
    src_pts = [(lat, lon) for lon, lat in src_lonlat]
    d1 = max(min_dist_to_polyline(p, src_pts) for p in osm_pts)
    d2 = max(min_dist_to_polyline(p, osm_pts) for p in src_pts)
    return max(d1, d2)


# ---------------------------------------------------------------------------
# Buffer width approximation — used to size the STRtree query window before
# we run the proper Hausdorff filter.
# ---------------------------------------------------------------------------

def polyline_length_m(geom_latlon: list[list[float]]) -> float:
    """Total length in metres of an OSM ``[[lat, lon], ...]`` polyline.

    Used by Phase 2a diagnostics to flag short ways (< 50 m) where the
    direction-alignment term has known noise.
    """
    if len(geom_latlon) < 2:
        return 0.0
    total = 0.0
    for i in range(len(geom_latlon) - 1):
        a_lat, a_lon = geom_latlon[i][0], geom_latlon[i][1]
        b_lat, b_lon = geom_latlon[i + 1][0], geom_latlon[i + 1][1]
        total += haversine_m(a_lat, a_lon, b_lat, b_lon)
    return total


def meters_to_degrees(meters: float) -> float:
    """Approximate buffer width in degrees.

    1 deg latitude ≈ 111_320 m; we use a slightly conservative bound so the
    candidate window slightly overshoots the geometric buffer (longitude
    degrees are smaller at Hamilton County's latitude, which makes the
    actual buffer *bigger* in practice — fine for candidate selection).
    """
    return meters / 111_000.0
