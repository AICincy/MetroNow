"""SORTA GTFS-Realtime feeds — direct Trapeze protobuf, no API key.

Complements the Transit App API client (:mod:`osm.transit`). That one
gives curated, quota-metered, multi-agency-normalized data and is the
primary path for network discovery and service alerts. This module
reads SORTA's own GTFS-RT feeds straight from the Trapeze backend
(``tmgtfsprd.sorttrpcloud.com``) where there is no quota and updates
land roughly every 15 seconds — the right source for vehicle positions
and trip updates, where the Transit App monthly quota would burn fast.

Feeds (verified 2026-05-11; all HTTP 200, no auth):

* ``vehicles`` — ``…/vehicle/vehiclepositions.pb``  (~11 KB)
* ``trips``    — ``…/tripupdate/tripupdates.pb``     (~310 KB)
* ``alerts``   — ``…/alert/alerts.pb``               (~26 KB) — not
  parsed here; service alerts go through :func:`osm.transit.fetch_sorta_alerts`
* ``combined`` — ``…/gtfs-realtime/trapezerealtimefeed.pb`` (~347 KB)

Parsing uses ``gtfs-realtime-bindings`` (``google.transit.gtfs_realtime_pb2``);
when that package is absent the module still imports and every fetch
returns ``[]``. Fail-open everywhere: network errors and malformed
payloads log, record a :mod:`osm.feed_errors` entry, fall back to a
stale on-disk copy if one exists, and ultimately return ``[]`` — the
audit pipeline never depends on GTFS-RT being reachable.

SORTA developer terms (``go-metro.com/about/developer-data``):
non-exclusive, revocable license; no SORTA trademarks without written
approval; data provided as-is; Ohio law governs.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feed endpoints + cache config
# ---------------------------------------------------------------------------

_TRAPEZE_BASE = (
    "https://tmgtfsprd.sorttrpcloud.com/TMGTFSRealTimeWebService"
)
FEED_URLS: dict[str, str] = {
    "vehicles": f"{_TRAPEZE_BASE}/vehicle/vehiclepositions.pb",
    "trips": f"{_TRAPEZE_BASE}/tripupdate/tripupdates.pb",
    "alerts": f"{_TRAPEZE_BASE}/alert/alerts.pb",
    "combined": f"{_TRAPEZE_BASE}/gtfs-realtime/trapezerealtimefeed.pb",
}

# Project User-Agent — same string the OSM + Transit clients use.
USER_AGENT = "MetroNow-OSM-Audit/0.1 (github.com/AICincy/MetroNow)"

# SORTA's feeds re-stamp Last-Modified roughly every 20-30 s, so a 30 s
# cache means repeated UI hits never poll faster than the feed updates.
# Upper bound — a fresh-cache hit is a free fetch. (The combined feed
# `…/gtfs-realtime/trapezerealtimefeed.pb` bundles vehicles + trip
# updates in one ~347 KB response; fetching it once instead of the two
# ~11 KB + ~310 KB feeds is a possible round-trip saving, not done here.)
CACHE_TTL_S = 30
CACHE_DIR = CONFIG_DIR / "gtfs_rt_cache"
REQUEST_TIMEOUT_S = 20


# ---------------------------------------------------------------------------
# Internals — protobuf import, fetch + cache, parse
# ---------------------------------------------------------------------------

def _import_pb():
    """Return the ``gtfs_realtime_pb2`` module, or ``None`` if not installed."""
    try:
        from google.transit import gtfs_realtime_pb2
        return gtfs_realtime_pb2
    except ImportError:
        log.warning(
            "gtfs-realtime-bindings not installed; SORTA GTFS-RT disabled.",
        )
        return None


def _cache_path(feed: str) -> Path:
    return CACHE_DIR / f"{feed}.pb"


def _fetch_raw(feed: str, *, force_refresh: bool = False) -> bytes | None:
    """GET the raw protobuf bytes for ``feed`` with a short on-disk cache.

    On a fetch error, falls back to a stale cached copy if one exists
    rather than returning nothing — a slightly old vehicle list beats
    none. Returns ``None`` only when there is no fresh data and no cache.
    """
    url = FEED_URLS.get(feed)
    if url is None:
        log.warning("Unknown GTFS-RT feed %r", feed)
        return None
    p = _cache_path(feed)
    if not force_refresh and p.exists():
        try:
            if (time.time() - p.stat().st_mtime) <= CACHE_TTL_S:
                return p.read_bytes()
        except OSError:
            pass
    try:
        # `.content` returns the raw bytes regardless of the response
        # content-type (SORTA serves `application/protocol-buffer`, not
        # the more common `application/x-protobuf` — irrelevant here, but
        # a gotcha for any client that sniffs the header).
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.content
    except requests.RequestException as exc:
        from . import feed_errors
        reason = (
            "timeout" if "timed out" in str(exc).lower() else "http_error"
        )
        feed_errors.record("gtfs_rt", reason, detail=f"{feed}: {exc}")
        log.warning("SORTA GTFS-RT %s fetch failed: %s", feed, exc)
        if p.exists():
            try:
                return p.read_bytes()
            except OSError:
                return None
        return None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except OSError as exc:
        log.warning("Could not cache GTFS-RT %s: %s", feed, exc)
    return data


def _parse(feed: str, *, force_refresh: bool = False):
    """Return a parsed ``FeedMessage`` for ``feed``, or ``None`` on any failure."""
    pb = _import_pb()
    if pb is None:
        return None
    raw = _fetch_raw(feed, force_refresh=force_refresh)
    if raw is None:
        return None
    try:
        msg = pb.FeedMessage()
        msg.ParseFromString(raw)
        return msg
    except Exception as exc:  # noqa: BLE001 — protobuf DecodeError + friends
        from . import feed_errors
        feed_errors.record("gtfs_rt", "decode_error", detail=f"{feed}: {exc}")
        log.warning("SORTA GTFS-RT %s parse failed: %s", feed, exc)
        return None


def _pos_int(value) -> int | None:
    """Coerce a protobuf timestamp/int to a positive int, else ``None``."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# ---------------------------------------------------------------------------
# Public — normalized feed accessors
# ---------------------------------------------------------------------------

def vehicle_positions(*, force_refresh: bool = False) -> list[dict]:
    """Normalized vehicle positions from SORTA's GTFS-RT feed, or ``[]``.

    Each item:
    ``{vehicle_id, trip_id, route_id, lat, lon, bearing, speed,
    timestamp, current_status, stop_id, occupancy}`` — fields not
    present in the feed entry are ``None``. ``current_status`` and
    ``occupancy`` are the raw GTFS-RT enum integers.
    """
    msg = _parse("vehicles", force_refresh=force_refresh)
    if msg is None:
        return []
    out: list[dict] = []
    for ent in msg.entity:
        if not ent.HasField("vehicle"):
            continue
        v = ent.vehicle
        pos = v.position if v.HasField("position") else None
        trip = v.trip if v.HasField("trip") else None
        out.append({
            "vehicle_id": (
                (v.vehicle.id or None) if v.HasField("vehicle") else None
            ),
            "trip_id": (trip.trip_id or None) if trip is not None else None,
            "route_id": (trip.route_id or None) if trip is not None else None,
            "lat": pos.latitude if pos is not None else None,
            "lon": pos.longitude if pos is not None else None,
            "bearing": (
                pos.bearing
                if pos is not None and pos.HasField("bearing")
                else None
            ),
            "speed": (
                pos.speed
                if pos is not None and pos.HasField("speed")
                else None
            ),
            "timestamp": (
                _pos_int(v.timestamp) if v.HasField("timestamp") else None
            ),
            "current_status": (
                int(v.current_status)
                if v.HasField("current_status")
                else None
            ),
            "stop_id": (v.stop_id or None) if v.HasField("stop_id") else None,
            "occupancy": (
                int(v.occupancy_status)
                if v.HasField("occupancy_status")
                else None
            ),
        })
    return out


def trip_updates(*, force_refresh: bool = False) -> list[dict]:
    """Normalized trip updates (stop-time predictions) from SORTA GTFS-RT, or ``[]``.

    Each item:
    ``{trip_id, route_id, vehicle_id, timestamp, stop_time_updates:
    [{stop_id, stop_sequence, arrival_time, arrival_delay,
    departure_time, departure_delay, schedule_relationship}]}``.
    ``arrival_delay`` / ``departure_delay`` are seconds (signed; positive
    = late). ``schedule_relationship`` is the raw GTFS-RT enum integer.
    """
    msg = _parse("trips", force_refresh=force_refresh)
    if msg is None:
        return []
    out: list[dict] = []
    for ent in msg.entity:
        if not ent.HasField("trip_update"):
            continue
        tu = ent.trip_update
        trip = tu.trip  # required field
        stus: list[dict] = []
        for stu in tu.stop_time_update:
            arr = stu.arrival if stu.HasField("arrival") else None
            dep = stu.departure if stu.HasField("departure") else None
            stus.append({
                "stop_id": (
                    (stu.stop_id or None) if stu.HasField("stop_id") else None
                ),
                "stop_sequence": (
                    int(stu.stop_sequence)
                    if stu.HasField("stop_sequence")
                    else None
                ),
                "arrival_time": (
                    _pos_int(arr.time)
                    if arr is not None and arr.HasField("time")
                    else None
                ),
                "arrival_delay": (
                    int(arr.delay)
                    if arr is not None and arr.HasField("delay")
                    else None
                ),
                "departure_time": (
                    _pos_int(dep.time)
                    if dep is not None and dep.HasField("time")
                    else None
                ),
                "departure_delay": (
                    int(dep.delay)
                    if dep is not None and dep.HasField("delay")
                    else None
                ),
                "schedule_relationship": (
                    int(stu.schedule_relationship)
                    if stu.HasField("schedule_relationship")
                    else None
                ),
            })
        out.append({
            "trip_id": trip.trip_id or None,
            "route_id": trip.route_id or None,
            "vehicle_id": (
                (tu.vehicle.id or None) if tu.HasField("vehicle") else None
            ),
            "timestamp": (
                _pos_int(tu.timestamp) if tu.HasField("timestamp") else None
            ),
            "stop_time_updates": stus,
        })
    return out


# Public feed names accepted by the CLI / web endpoint.
NORMALIZED_FEEDS: dict[str, str] = {
    "vehicles": "vehicle_positions",
    "trips": "trip_updates",
}


def fetch(feed: str, *, force_refresh: bool = False) -> list[dict]:
    """Dispatch to the normalized accessor for ``feed`` (``vehicles`` / ``trips``).

    Returns ``[]`` for an unknown feed name as well as on any fetch /
    parse failure — callers treat ``[]`` as "GTFS-RT unavailable".
    """
    if feed == "vehicles":
        return vehicle_positions(force_refresh=force_refresh)
    if feed == "trips":
        return trip_updates(force_refresh=force_refresh)
    log.warning("Unknown normalized GTFS-RT feed %r (want vehicles|trips)", feed)
    return []


__all__ = [
    "CACHE_DIR",
    "CACHE_TTL_S",
    "FEED_URLS",
    "NORMALIZED_FEEDS",
    "USER_AGENT",
    "fetch",
    "trip_updates",
    "vehicle_positions",
]
