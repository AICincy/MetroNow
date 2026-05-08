"""MOTIS routing-engine client (prototype).

A defensive HTTP client for a self-hosted MOTIS instance
(``https://github.com/motis-project/motis``). MOTIS's advantage over
BRouter for MetroNow's purposes is **multi-modal routing**: it ingests
OSM and GTFS in the same graph, so a route between two stops can
reflect both walking-network changes (the BRouter case) AND transit
schedule effects in a single comparison. That makes it the right
engine for downstream "what if SORTA changed this corridor's frequency
on its next ingest" questions, where BRouter is car-only.

This module is intentionally minimal:

* :func:`fetch_route` returns the same ``{length_m, duration_s, cost,
  geometry}`` shape as :func:`osm.route_diff.fetch_route` so the
  BRouter→MOTIS swap downstream is a one-line dispatcher change.
* The MOTIS endpoint URL is configurable via the ``MOTIS_BASE`` env
  var; default is ``http://localhost:8080`` (MOTIS's documented
  default port).
* Fail-open: any HTTP / JSON / connection error logs and returns
  ``None``. The pipeline degrades to BRouter-only just like it does
  on Transit-API failures.
* Cached identically to BRouter: 24-hour TTL keyed by (origin,
  destination, mode) under ``~/.config/osm/motis_cache/``.

There is **no MOTIS server bundled** — operators must either point
``MOTIS_BASE`` at a hosted instance or stand up their own following
the deployment notes in ``docs/motis-deployment.md`` (added in this
commit). Until then, ``fetch_route`` will return ``None`` and any
caller that uses the MOTIS engine will silently fall back.

Endpoint reference: ``/api/v5/plan`` (OpenAPI spec at
https://raw.githubusercontent.com/motis-project/motis/master/openapi.yaml).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import time
from pathlib import Path

import requests

from .config import CONFIG_DIR

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# MOTIS's documented default port. Override via the MOTIS_BASE env var.
MOTIS_DEFAULT_BASE = "http://localhost:8080"

# Cache lives alongside the BRouter cache; same 24-hour TTL.
MOTIS_CACHE_DIR = CONFIG_DIR / "motis_cache"
MOTIS_CACHE_TTL_S = 24 * 3_600

MOTIS_HEADERS = {
    "User-Agent": "MetroNow-OSM-Audit/0.1 (github.com/AICincy/MetroNow)",
    "Accept": "application/json",
}

# Default mode strings — match MOTIS v5 conventions.
DEFAULT_DIRECT_MODES = ("WALK",)
DEFAULT_TRANSIT_MODES = ("TRANSIT",)


def _base_url() -> str:
    return os.environ.get("MOTIS_BASE", MOTIS_DEFAULT_BASE).rstrip("/")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str,
) -> str:
    raw = json.dumps(
        {"o": list(origin), "d": list(destination), "m": mode},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    return MOTIS_CACHE_DIR / f"plan-{key}.json"


def _read_cached(key: str) -> dict | None:
    p = _cache_path(key)
    if not p.exists():
        return None
    if (time.time() - p.stat().st_mtime) > MOTIS_CACHE_TTL_S:
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_cached(key: str, payload: dict) -> None:
    try:
        MOTIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(key).open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except OSError as exc:
        log.warning("Could not write MOTIS cache: %s", exc)


# ---------------------------------------------------------------------------
# Polyline decoding — MOTIS v5 returns Google polylines at precision=6
# ---------------------------------------------------------------------------

def decode_polyline(encoded: str, *, precision: int = 6) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline into a list of ``(lon, lat)`` pairs.

    MOTIS v5 emits polylines at precision=6 (vs Google's default of 5),
    so the divisor is ``10**precision``. We return ``(lon, lat)`` to
    match the rest of the pipeline's convention; the polyline format
    encodes ``(lat, lon)``.
    """
    if not encoded:
        return []
    coords: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lon = 0
    factor = 10 ** precision
    n = len(encoded)
    while index < n:
        # latitude
        result = 0
        shift = 0
        while True:
            if index >= n:
                return coords
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += ((~(result >> 1)) if (result & 1) else (result >> 1))
        # longitude
        result = 0
        shift = 0
        while True:
            if index >= n:
                return coords
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lon += ((~(result >> 1)) if (result & 1) else (result >> 1))
        coords.append((lon / factor, lat / factor))
    return coords


# ---------------------------------------------------------------------------
# /api/v5/plan
# ---------------------------------------------------------------------------

def fetch_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    mode: str = "WALK",
    when: _dt.datetime | None = None,
    timeout: int = 30,
    use_cache: bool = True,
) -> dict | None:
    """One MOTIS ``/api/v5/plan`` call.

    ``origin`` and ``destination`` are ``(lon, lat)`` tuples to match
    the rest of the pipeline. MOTIS expects ``"lat,lon"`` strings, so
    the order is flipped at the wire.

    ``mode`` is a single MOTIS mode string. Common values: ``"WALK"``,
    ``"BIKE"``, ``"CAR"``, ``"TRANSIT"``. For multi-modal queries pass
    ``"TRANSIT"`` and let MOTIS chain in walking legs from the GTFS
    transfers table.

    Returns ``{'length_m', 'duration_s', 'cost', 'geometry'}`` or
    ``None`` on any error (HTTP, timeout, no itinerary, MOTIS not
    deployed). ``geometry`` is a list of ``(lon, lat)`` pairs decoded
    from the first itinerary's first leg polyline. ``cost`` mirrors
    BRouter: it equals ``duration_s`` for the MOTIS prototype since
    MOTIS doesn't expose a comparable graph cost.
    """
    when = when or _dt.datetime.now(_dt.UTC)
    key = _cache_key(origin, destination, mode)
    if use_cache:
        cached = _read_cached(key)
        if cached is not None:
            return cached

    # MOTIS expects "lat,lon" — pipeline uses "lon,lat" everywhere else.
    o_lat, o_lon = origin[1], origin[0]
    d_lat, d_lon = destination[1], destination[0]
    params: dict[str, str] = {
        "fromPlace": f"{o_lat},{o_lon}",
        "toPlace": f"{d_lat},{d_lon}",
        "time": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # MOTIS treats mode-class differently — direct vs transit. WALK / BIKE /
    # CAR live under directModes; TRANSIT under transitModes. Anything else
    # we punt to direct.
    if mode.upper() == "TRANSIT":
        params["transitModes"] = "TRANSIT"
        params["directModes"] = "WALK"
    else:
        params["directModes"] = mode.upper()

    url = _base_url() + "/api/v5/plan"
    try:
        resp = requests.get(
            url, params=params, headers=MOTIS_HEADERS, timeout=timeout,
        )
    except requests.RequestException as exc:
        log.info("MOTIS request failed (%s); falling back. URL=%s", exc, url)
        return None

    if resp.status_code >= 400:
        log.info(
            "MOTIS HTTP %d for %s -> %s: %s",
            resp.status_code, origin, destination,
            (resp.text or "")[:160],
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        log.info(
            "MOTIS returned non-JSON for %s -> %s: %s",
            origin, destination, (resp.text or "")[:160],
        )
        return None

    parsed = _parse_plan_response(data)
    if parsed is None:
        return None
    if use_cache:
        _write_cached(key, parsed)
    return parsed


def _parse_plan_response(data: dict) -> dict | None:
    """Extract the standard pipeline shape from a /plan response.

    Picks the first itinerary, sums leg distances and durations, and
    decodes the first leg's polyline as the geometry. Returns
    ``None`` when no itinerary is present (= unreachable).
    """
    itineraries = (data or {}).get("itineraries") or []
    if not itineraries:
        return None
    itin = itineraries[0]
    legs = itin.get("legs") or []
    if not legs:
        return None

    length_m = 0.0
    geometry: list[tuple[float, float]] = []
    for leg in legs:
        d = leg.get("distance")
        if isinstance(d, (int, float)):
            length_m += float(d)
        # Decode polyline. MOTIS v5 puts the encoded string at
        # legGeometry.points; precision varies by API version.
        lg = leg.get("legGeometry") or {}
        points = lg.get("points")
        precision = lg.get("precision") or 6
        if isinstance(points, str):
            geometry.extend(decode_polyline(points, precision=int(precision)))

    # Duration: prefer the itinerary-level duration (seconds). Falling
    # back to startTime/endTime arithmetic keeps us robust to schema drift.
    duration_s = itin.get("duration")
    if not isinstance(duration_s, (int, float)):
        start = _parse_iso(itin.get("startTime"))
        end = _parse_iso(itin.get("endTime"))
        duration_s = (end - start).total_seconds() if start and end else 0.0
    duration_s = float(duration_s)

    return {
        "length_m": length_m,
        "duration_s": duration_s,
        # BRouter exposes a graph cost; MOTIS doesn't surface a comparable
        # scalar, so we mirror duration_s. Kept as a separate field so
        # downstream diffs can be retargeted later.
        "cost": duration_s,
        "geometry": geometry,
    }


def _parse_iso(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Health probe — used by the route-diff CLI to decide whether to engage MOTIS
# ---------------------------------------------------------------------------

def is_available(timeout: int = 5) -> bool:
    """``True`` if a MOTIS instance answers /api/v5/plan at MOTIS_BASE.

    Sends a near-trivial query (origin == destination) so the response
    is small. Does not raise; logs at info on failure and returns
    ``False`` so callers can degrade silently.
    """
    url = _base_url() + "/api/v5/plan"
    try:
        resp = requests.get(
            url,
            params={
                "fromPlace": "39.20,-84.39",
                "toPlace": "39.20,-84.39",
                "time": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "directModes": "WALK",
            },
            headers=MOTIS_HEADERS,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        log.info("MOTIS health probe failed at %s: %s", url, exc)
        return False
    return resp.status_code < 500
