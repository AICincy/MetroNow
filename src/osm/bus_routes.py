"""SORTA bus-route loader for transit-corridor corroboration.

Phase 4d follow-up: when a rider-impact detector finding (currently
``oneway_conflict``) lies on a SORTA bus-route corridor, the
defect's routing impact is materially higher than on a residential
side street. Riding buses use the corridor on a published schedule;
ViaAlgo and SORTA share the same OSM data, so a misconfigured oneway
that breaks fixed-route buses likely breaks MetroNow on-demand routing
too.

This module is a small mirror of :mod:`osm.gtfs`: fetch the CAGIS-
hosted bus-routes FeatureServer (Esri), parse polylines, cache for a
week. The detector path then queries ``is_on_transit_corridor(way,
bus_routes)`` to mark findings as transit-coincident.

Source: ArcGIS Online item ``af1e72d1373a4ceab400aa4fd2bc8173`` /
``data-cagisportal.opendata.arcgis.com/datasets/af1e72d1373a4ceab400aa4fd2bc8173_46``
("METRO Bus Routes — Open Data", owner ``cagisopendata``, public).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import requests

from .cache import is_cache_fresh
from .config import CONFIG_DIR
from .geo import haversine_m

log = logging.getLogger(__name__)

CAGIS_BUS_ROUTES_URL = (
    "https://services.arcgis.com/JyZag7oO4NteHGiq/arcgis/rest/services/"
    "Open_Data/FeatureServer/46/query"
)

BUS_ROUTES_CACHE_DIR = CONFIG_DIR / "bus_routes_cache"
BUS_ROUTES_CACHE = BUS_ROUTES_CACHE_DIR / "sorta_bus_routes.json"
BUS_ROUTES_CACHE_TTL_DAYS = 7

# Default match threshold: a way whose midpoint is within this many
# metres of any bus-route polyline counts as on a transit corridor.
TRANSIT_CORRIDOR_THRESHOLD_M = 25.0


@dataclass
class BusRoute:
    """One row from the CAGIS METRO Bus Routes FeatureServer."""

    route_id: str
    route_short: str
    route_long: str
    # Polyline as list of [lat, lon] pairs (in-pipeline order).
    geometry_latlon: list[tuple[float, float]]


def _features_to_bus_routes(geojson: dict) -> list[BusRoute]:
    out: list[BusRoute] = []
    for feat in geojson.get("features", []):
        p = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        if gtype == "LineString":
            rings = [geom.get("coordinates", [])]
        elif gtype == "MultiLineString":
            rings = geom.get("coordinates", [])
        else:
            continue
        for ring in rings:
            pts: list[tuple[float, float]] = []
            for coord in ring:
                if len(coord) < 2:
                    continue
                # GeoJSON is [lon, lat]; project to [lat, lon].
                pts.append((float(coord[1]), float(coord[0])))
            if len(pts) < 2:
                continue
            out.append(BusRoute(
                route_id=str(p.get("ROUTE_ID") or ""),
                route_short=str(p.get("ROUTE_SHOR") or ""),
                route_long=str(p.get("ROUTE_LONG") or ""),
                geometry_latlon=pts,
            ))
    return out


def fetch_bus_routes(
    *, force_refresh: bool = False, timeout: int = 60,
) -> list[BusRoute]:
    """Return SORTA's published bus-route polylines, cached for a week.

    Cache miss / stale → fetch the FeatureServer GeoJSON, parse, persist.
    Network failure → fall back to the on-disk cache regardless of age.
    """
    if not force_refresh and is_cache_fresh(
        BUS_ROUTES_CACHE, BUS_ROUTES_CACHE_TTL_DAYS * 86_400,
    ):
        try:
            with BUS_ROUTES_CACHE.open("r", encoding="utf-8") as fh:
                geojson = json.load(fh)
            routes = _features_to_bus_routes(geojson)
            log.info(
                "SORTA bus routes: loaded %d shape(s) from cache", len(routes),
            )
            return routes
        except (OSError, json.JSONDecodeError) as exc:
            log.warning(
                "Bus-routes cache unreadable (%s); re-fetching.", exc,
            )

    log.info("SORTA bus routes: fetching %s", CAGIS_BUS_ROUTES_URL)
    try:
        resp = requests.get(
            CAGIS_BUS_ROUTES_URL,
            params={
                "where": "1=1",
                "outFields": "ROUTE_ID,ROUTE_SHOR,ROUTE_LONG",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        geojson = resp.json()
        routes = _features_to_bus_routes(geojson)
        log.info("SORTA bus routes: parsed %d shape(s)", len(routes))
        try:
            BUS_ROUTES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with BUS_ROUTES_CACHE.open("w", encoding="utf-8") as fh:
                json.dump(geojson, fh, ensure_ascii=False)
        except OSError as exc:
            log.warning("Could not write bus-routes cache: %s", exc)
        return routes
    except (requests.RequestException, ValueError) as exc:
        log.warning(
            "Bus-routes fetch failed (%s); trying stale cache.", exc,
        )
        if BUS_ROUTES_CACHE.exists():
            try:
                with BUS_ROUTES_CACHE.open("r", encoding="utf-8") as fh:
                    geojson = json.load(fh)
                routes = _features_to_bus_routes(geojson)
                age_s = time.time() - BUS_ROUTES_CACHE.stat().st_mtime
                log.warning(
                    "SORTA bus routes: using stale cache (%.1f days old)",
                    age_s / 86_400,
                )
                return routes
            except (OSError, json.JSONDecodeError):
                pass
        return []


def _way_midpoint_latlon(way: dict) -> tuple[float, float] | None:
    """Best-effort midpoint of an OSM way's geometry as (lat, lon)."""
    geom = way.get("geometry") or []
    if not geom:
        return None
    mid = geom[len(geom) // 2]
    if isinstance(mid, dict):
        lat = mid.get("lat")
        lon = mid.get("lon")
    else:
        lat, lon = mid[0], mid[1]
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return (float(lat), float(lon))
    return None


def is_on_transit_corridor(
    way: dict,
    bus_routes: list[BusRoute],
    *,
    threshold_m: float = TRANSIT_CORRIDOR_THRESHOLD_M,
) -> tuple[bool, list[str]]:
    """True if ``way`` lies within ``threshold_m`` of any SORTA bus route.

    Returns ``(is_corridor, route_ids)`` — the second element is a list
    of matching ROUTE_ID values for downstream attribution.

    Uses a coarse lat/lon bbox prefilter then haversine to one segment
    midpoint per polyline; this is good enough for "is this corridor
    served by a published bus route" without paying the cost of a full
    point-to-line projection on 200+ shapes.
    """
    mid = _way_midpoint_latlon(way)
    if mid is None or not bus_routes:
        return (False, [])
    way_lat, way_lon = mid
    matched: list[str] = []
    # Coarse bbox: skip routes whose midpoint is more than ~0.01 deg
    # (~1.1 km) from the way's midpoint. Bus-route shapes are long but
    # their midpoint is usually within range when the way is on the
    # corridor.
    for r in bus_routes:
        if not r.geometry_latlon:
            continue
        rmid = r.geometry_latlon[len(r.geometry_latlon) // 2]
        if abs(rmid[0] - way_lat) > 0.05 and abs(rmid[1] - way_lon) > 0.05:
            continue
        # Find nearest vertex of the route polyline.
        best = None
        for plat, plon in r.geometry_latlon:
            if abs(plat - way_lat) > 0.005 and abs(plon - way_lon) > 0.005:
                continue
            d = haversine_m(way_lat, way_lon, plat, plon)
            if best is None or d < best:
                best = d
        if best is not None and best <= threshold_m:
            matched.append(r.route_id or r.route_short or "?")
    return (bool(matched), matched)
