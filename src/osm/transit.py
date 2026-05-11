"""Transit App API v4 client (rate-limited, quota-tracked, fail-open).

Phase 4c follow-up: a defensive client for the Transit App developer
API (https://api-doc.transitapp.com/v4.html). The tier here is
5,000 calls/month (uplifted from the 1,500 public tier) and 5
calls/minute — so this client is designed around quota preservation:

* Aggressive on-disk caching keyed by endpoint + query, with TTLs
  matched to each endpoint class (24 h for static metadata, 30 s
  floor for real-time)
* Token-bucket pacing at the 5/minute hard cap
* Local monthly quota counter at
  ``~/.config/osm/transit_api_usage.json``; the client refuses to
  call once it sees ``QUOTA_BUDGET_FRACTION`` (default 80 %) of the
  quota consumed, leaving headroom for the rest of the month
* Fail-open: any quota or network error logs and returns ``None``
  rather than raising — the main scan/fix path is never blocked by
  Transit unavailability

The API key lives at ``~/.config/osm/transit_api.json`` (chmod 600,
shape ``{"api_key": "..."}``); never logged, never in error
messages, never in the repo.

Terms of service obligations the calling code MUST honour:

* Display "Powered by Transit" attribution in any UI surface that
  renders Transit data
* Identify with a User-Agent matching the project repo
* Notify ``apis@transitapp.com`` at least 10 business days before
  any public release of a tool that uses this client

See ``docs/community-prep/05-transit-api-compliance.md`` for the
full obligation list and the maintainer's runbook.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — endpoint / cache / quota configuration
# ---------------------------------------------------------------------------

TRANSIT_BASE_URL = "https://external.transitapp.com/v4/public"

# Per Transit's email at API key issuance, plus the 2026-05-11 uplift.
RATE_LIMIT_PER_MINUTE = 5
MONTHLY_QUOTA_FREE_TIER = 5_000  # 1,500 public tier + civic uplift
QUOTA_BUDGET_FRACTION = 0.80  # refuse calls past 80 % of quota

# Header name from api-doc.transitapp.com/v4.html (securitySchemes.apiKey).
AUTH_HEADER = "apiKey"

# Project User-Agent — required by Transit ToS for traceability.
USER_AGENT = (
    "MetroNow-OSM-Audit/0.1 (github.com/AICincy/MetroNow)"
)

# "Powered by Transit" attribution string for any UI surface that
# renders Transit data. Matches Transit's brand-asset wording.
POWERED_BY_TRANSIT_ATTRIBUTION = "Powered by Transit"

# Endpoint TTLs (seconds). Static metadata can cache for a day; real-time
# departures and vehicle positions need a much shorter floor. These are
# upper bounds — a fresh-cache hit is free quota.
TTL_BY_ENDPOINT: dict[str, int] = {
    "available_networks": 7 * 86_400,         # quarterly at most
    "routes_for_networks": 24 * 3_600,        # daily refresh fine
    "stops_for_network": 24 * 3_600,
    "route_details": 24 * 3_600,
    "search_stops": 6 * 3_600,
    "nearby_stops": 24 * 3_600,
    "nearby_routes": 24 * 3_600,
    "stop_departures": 60,                    # 1-minute floor for arrivals
    "trip_details": 60,
    "alerts_for_networks": 5 * 60,            # 5-minute polling on alerts
    "latest_update_for_network": 24 * 3_600,
    "plan": 6 * 3_600,                        # trip plans stable enough for hours
    "estimate_plan_duration": 6 * 3_600,
}

# File locations — same neighbourhood as OAuth + GTFS + bus-routes caches.
KEY_FILE = CONFIG_DIR / "transit_api.json"
USAGE_FILE = CONFIG_DIR / "transit_api_usage.json"
CACHE_DIR = CONFIG_DIR / "transit_cache"


# ---------------------------------------------------------------------------
# Auth & key loading
# ---------------------------------------------------------------------------

@dataclass
class TransitClientStatus:
    """Quick health check used by callers and the CLI 'transit status'."""

    has_key: bool
    monthly_quota: int
    used_this_month: int
    budget_cap: int
    quota_exhausted: bool
    cache_dir_exists: bool


def _load_api_key() -> str | None:
    """Read the API key from the file at KEY_FILE.

    Returns ``None`` when the file is missing or malformed — callers
    must treat this as "Transit is unavailable" and degrade.
    """
    if not KEY_FILE.exists():
        return None
    try:
        with KEY_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        key = (data or {}).get("api_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Transit API key file unreadable (%s).", exc)
    return None


# ---------------------------------------------------------------------------
# Rate limiting + monthly quota counter
# ---------------------------------------------------------------------------

# Process-level rate-limit state. Persisted across calls within the same
# Python process; deliberately NOT persisted to disk because the 5/min
# cap is per-network not per-process and a stale on-disk counter could
# block legitimate calls after a long pause.
_recent_calls: list[float] = []


def _rate_limit_pace() -> None:
    """Block until at least one call slot is free in the 60-second window.

    Token-bucket implementation: track the timestamps of the last
    ``RATE_LIMIT_PER_MINUTE`` calls; if all five are within the past
    60 seconds, sleep until the oldest expires.
    """
    now = time.monotonic()
    horizon = now - 60.0
    # Drop expired slots
    while _recent_calls and _recent_calls[0] < horizon:
        _recent_calls.pop(0)
    if len(_recent_calls) >= RATE_LIMIT_PER_MINUTE:
        sleep_for = 60.0 - (now - _recent_calls[0]) + 0.1
        if sleep_for > 0:
            log.info("Transit rate-limit: sleeping %.1fs", sleep_for)
            time.sleep(sleep_for)
    _recent_calls.append(time.monotonic())


def _current_month_key() -> str:
    """YYYY-MM in UTC for the monthly quota counter."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m")


def _read_usage() -> dict:
    if not USAGE_FILE.exists():
        return {"month": _current_month_key(), "count": 0}
    try:
        with USAGE_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Reset counter on month rollover
        if data.get("month") != _current_month_key():
            data = {"month": _current_month_key(), "count": 0}
        return data
    except (OSError, json.JSONDecodeError):
        return {"month": _current_month_key(), "count": 0}


def _write_usage(data: dict) -> None:
    try:
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_FILE.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except OSError as exc:
        log.warning("Could not write Transit usage counter: %s", exc)


def _budget_cap() -> int:
    """Effective per-month call cap (quota × budget fraction)."""
    return int(MONTHLY_QUOTA_FREE_TIER * QUOTA_BUDGET_FRACTION)


def _quota_exhausted() -> bool:
    """True when the local counter has reached the budget cap."""
    return _read_usage().get("count", 0) >= _budget_cap()


def _increment_usage() -> None:
    """Atomically increment the monthly call counter.

    Concurrent scans (CLI + web server invoking the client at the same
    time) could otherwise lose updates via interleaved read-modify-write.
    On POSIX we hold an exclusive ``fcntl.flock`` on a sibling lock file
    for the duration of the read+write; on platforms without ``fcntl``
    the lock degrades to a no-op (tradeoff: better than corrupting the
    counter on Linux for the sake of Windows symmetry).
    """
    try:
        import fcntl  # POSIX-only; Windows users get the unlocked path
    except ImportError:
        data = _read_usage()
        data["count"] = int(data.get("count", 0)) + 1
        _write_usage(data)
        return

    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = USAGE_FILE.with_suffix(USAGE_FILE.suffix + ".lock")
    try:
        with lock_path.open("a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                data = _read_usage()
                data["count"] = int(data.get("count", 0)) + 1
                _write_usage(data)
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        log.warning("Could not acquire Transit usage lock: %s", exc)
        # Fall back to unlocked update — better than dropping the increment
        data = _read_usage()
        data["count"] = int(data.get("count", 0)) + 1
        _write_usage(data)


def status() -> TransitClientStatus:
    """Lightweight health snapshot — no network calls."""
    usage = _read_usage()
    return TransitClientStatus(
        has_key=_load_api_key() is not None,
        monthly_quota=MONTHLY_QUOTA_FREE_TIER,
        used_this_month=int(usage.get("count", 0)),
        budget_cap=_budget_cap(),
        quota_exhausted=_quota_exhausted(),
        cache_dir_exists=CACHE_DIR.exists(),
    )


# ---------------------------------------------------------------------------
# On-disk cache
# ---------------------------------------------------------------------------

def _cache_key(endpoint: str, params: dict | None) -> str:
    """Stable hash of (endpoint, params) for the cache filename."""
    raw = endpoint + "|" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(endpoint: str, params: dict | None) -> Path:
    return CACHE_DIR / f"{endpoint}_{_cache_key(endpoint, params)}.json"


def _read_cached(endpoint: str, params: dict | None) -> dict | None:
    p = _cache_path(endpoint, params)
    if not p.exists():
        return None
    ttl = TTL_BY_ENDPOINT.get(endpoint, 3_600)
    try:
        if (time.time() - p.stat().st_mtime) > ttl:
            return None
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _write_cached(endpoint: str, params: dict | None, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(endpoint, params).open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except OSError as exc:
        log.warning("Could not write Transit cache for %s: %s", endpoint, exc)


# ---------------------------------------------------------------------------
# Core request — every endpoint helper goes through this
# ---------------------------------------------------------------------------

def _request(
    endpoint: str,
    params: dict | None = None,
    *,
    force_refresh: bool = False,
    timeout: int = 30,
) -> dict | None:
    """GET ``/v4/public/{endpoint}`` and return parsed JSON.

    Returns ``None`` (with a warning log) on any of: missing API key,
    quota exhaustion, network failure, non-2xx response, malformed
    JSON. The main pipeline must treat ``None`` as "Transit data
    unavailable" and degrade gracefully.

    Cache hits do not count against the monthly quota.
    """
    if not force_refresh:
        cached = _read_cached(endpoint, params)
        if cached is not None:
            log.debug("Transit cache hit: %s", endpoint)
            return cached

    api_key = _load_api_key()
    if not api_key:
        log.warning(
            "Transit API key not configured; %s skipped. "
            "Add to %s.", endpoint, KEY_FILE,
        )
        return None
    if _quota_exhausted():
        log.warning(
            "Transit monthly quota at budget cap (%d / %d); %s skipped.",
            _read_usage().get("count", 0), _budget_cap(), endpoint,
        )
        return None

    _rate_limit_pace()
    url = f"{TRANSIT_BASE_URL}/{endpoint}"
    headers = {AUTH_HEADER: api_key, "User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        _increment_usage()  # count even on error responses — Transit does
        if resp.status_code == 429:
            from . import feed_errors
            feed_errors.record("transit", "rate_limit",
                               detail=f"{endpoint} returned 429")
            log.warning(
                "Transit returned 429 for %s; rate limit hit despite pacing.",
                endpoint,
            )
            return None
        resp.raise_for_status()
        payload = resp.json()
        _write_cached(endpoint, params, payload)
        return payload
    except (requests.RequestException, ValueError) as exc:
        from . import feed_errors
        reason = "timeout" if "timed out" in str(exc).lower() else (
            "non_json" if isinstance(exc, ValueError) else "http_error"
        )
        feed_errors.record("transit", reason, detail=f"{endpoint}: {exc}")
        log.warning("Transit %s failed: %s", endpoint, exc)
        return None


# ---------------------------------------------------------------------------
# Endpoint helpers — typed wrappers around _request()
# ---------------------------------------------------------------------------

def available_networks(*, force_refresh: bool = False) -> dict | None:
    """Discover available Transit networks. Used to find SORTA's network_id."""
    return _request("available_networks", force_refresh=force_refresh)


def nearby_stops(
    lat: float,
    lon: float,
    *,
    max_distance: int = 500,
    force_refresh: bool = False,
) -> dict | None:
    """Stops within ``max_distance`` metres of (lat, lon).

    Used by the Transit cross-check to validate `misplaced_bus_stops`
    findings against authoritative stop data.
    """
    return _request(
        "nearby_stops",
        params={"lat": lat, "lon": lon, "max_distance": max_distance},
        force_refresh=force_refresh,
    )


def stop_departures(
    global_stop_id: str,
    *,
    max_num_departures: int = 10,
    force_refresh: bool = False,
) -> dict | None:
    """Real-time departures for a stop. Counts against quota every minute."""
    return _request(
        "stop_departures",
        params={
            "global_stop_id": global_stop_id,
            "max_num_departures": max_num_departures,
        },
        force_refresh=force_refresh,
    )


def alerts_for_networks(
    global_network_ids: list[str],
    *,
    force_refresh: bool = False,
) -> dict | None:
    """Service alerts for one or more networks (e.g. SORTA's network)."""
    return _request(
        "alerts_for_networks",
        params={"global_network_ids": ",".join(global_network_ids)},
        force_refresh=force_refresh,
    )


def trip_plan(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    *,
    force_refresh: bool = False,
) -> dict | None:
    """Trip plan between two coordinates. Used for fix-impact sampling."""
    return _request(
        "plan",
        params={
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "dest_lat": dest_lat,
            "dest_lon": dest_lon,
        },
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# Pipeline integration — cross-checks that consume the endpoint helpers
# ---------------------------------------------------------------------------

def _stop_latlon(stop: dict) -> tuple[float, float] | None:
    """Pull (lat, lon) from a Transit ``nearby_stops`` stop record.

    The v4 payload uses ``stop_lat`` / ``stop_lon``; tolerate the bare
    ``lat`` / ``lon`` spelling too so a payload-shape tweak upstream
    doesn't silently disable the cross-check.
    """
    raw_lat = stop.get("stop_lat")
    if raw_lat is None:
        raw_lat = stop.get("lat")
    raw_lon = stop.get("stop_lon")
    if raw_lon is None:
        raw_lon = stop.get("lon")
    if raw_lat is None or raw_lon is None:
        return None
    try:
        return float(raw_lat), float(raw_lon)
    except (TypeError, ValueError):
        return None


def cross_check_bus_stop_findings(
    findings: list[dict],
    *,
    match_threshold_m: float = 50.0,
    max_distance_m: int = 200,
) -> tuple[list[dict], int]:
    """Suppress ``bus_stop_misplaced`` findings that Transit corroborates.

    For each ``kind == "bus_stop_misplaced"`` finding with usable
    coordinates, query Transit's ``nearby_stops`` around it. If Transit
    knows a stop within ``match_threshold_m``, the OSM placement is a
    valid off-curb shelter — the same false-positive class the GTFS
    cross-check in :func:`osm.detectors.detect_misplaced_bus_stops`
    suppresses — so the finding is dropped.

    Returns ``(kept_findings, n_suppressed)``. One ``nearby_stops`` call
    per flagged candidate; flagged stops are a small subset of all stops
    in a zone, so this stays well inside the monthly quota. Fail-open:
    when the client has no key, is quota-exhausted, or errors,
    ``nearby_stops`` returns ``None`` and the finding is kept untouched.
    Non-``bus_stop_misplaced`` findings and findings without a usable
    coordinate pass through without an API call.
    """
    if not findings:
        return findings, 0

    from .geo import haversine_m, valid_latlon

    kept: list[dict] = []
    n_suppressed = 0
    for f in findings:
        if f.get("kind") != "bus_stop_misplaced":
            kept.append(f)
            continue
        lat = f.get("lat")
        lon = f.get("lon")
        if lat is None or lon is None:
            kept.append(f)
            continue
        try:
            flat, flon = float(lat), float(lon)
        except (TypeError, ValueError):
            kept.append(f)
            continue
        if not valid_latlon(flat, flon):
            kept.append(f)
            continue

        resp = nearby_stops(flat, flon, max_distance=max_distance_m)
        if not resp:
            kept.append(f)
            continue

        best: float | None = None
        for stop in resp.get("stops") or []:
            sll = _stop_latlon(stop) if isinstance(stop, dict) else None
            if sll is None or not valid_latlon(*sll):
                continue
            d = haversine_m(flat, flon, sll[0], sll[1])
            if best is None or d < best:
                best = d
        if best is not None and best <= match_threshold_m:
            n_suppressed += 1
            continue
        kept.append(f)
    return kept, n_suppressed


# SORTA's identity in Transit's network catalog. Transit's v4 docs don't
# publish the per-agency global_network_id, so resolve_sorta_network_id()
# matches network metadata against these (case-insensitive) substrings;
# `osm transit-networks` dumps the full catalog if the heuristic misses.
# Kept conservative on purpose — a wrong match would fetch some other
# agency's alerts. SORTA = Southwest Ohio Regional Transit Authority,
# brand "Cincinnati Metro" (go-metro.com). Catalog IDs that should
# match: Transitland operator `o-dngy-southwestohioregionaltransitauthority`
# (geohash prefix `dngy` = the Cincinnati cell) and feed
# `f-cincinnatimetro` / `f-cincinnatimetro~rt`; Mobility Database
# `mdb-366`. Bare "metro" is deliberately excluded — far too broad.
SORTA_NETWORK_HINTS: tuple[str, ...] = (
    "sorta",
    "cincinnatimetro",
    "cincinnati metro",
    "southwest ohio regional transit",
    "go-metro",
    "gometro",
    "dngy",
)


def _network_id(net: dict) -> str | None:
    """First non-empty network-id-shaped field in a catalog record."""
    for key in ("global_network_id", "network_id", "id"):
        v = net.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _network_match_fields(net: dict) -> list[str]:
    """Lowercased strings from a network record to match SORTA against."""
    out: list[str] = []
    for key in (
        "global_network_id", "network_id", "id",
        "network_name", "name", "network_short_name", "short_name",
    ):
        v = net.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v.strip().lower())
    for agency in net.get("agencies") or []:
        if isinstance(agency, dict):
            v = agency.get("agency_name") or agency.get("name")
            if isinstance(v, str) and v.strip():
                out.append(v.strip().lower())
    return out


def resolve_sorta_network_id(*, force_refresh: bool = False) -> str | None:
    """Best-effort lookup of SORTA's ``global_network_id`` in Transit's catalog.

    Calls ``available_networks`` (itself 7-day-cached, so this is cheap)
    and returns the id of the first network whose metadata matches a
    :data:`SORTA_NETWORK_HINTS` substring. Returns ``None`` when Transit
    is unavailable or nothing matched — callers treat that as "alerts
    unavailable" and degrade. Run ``osm transit-networks`` to inspect
    the catalog if the heuristic picks the wrong network or nothing.
    """
    payload = available_networks(force_refresh=force_refresh)
    if not payload:
        return None
    networks = payload.get("networks")
    if not isinstance(networks, list):
        return None
    for net in networks:
        if not isinstance(net, dict):
            continue
        fields = _network_match_fields(net)
        if any(hint in field for field in fields for hint in SORTA_NETWORK_HINTS):
            nid = _network_id(net)
            if nid:
                log.info("Transit: resolved SORTA network id to %s", nid)
                return nid
    log.warning(
        "Transit: no network matched SORTA hints in available_networks; "
        "run 'osm transit-networks' to inspect the catalog.",
    )
    return None


def _normalize_alerts(payload: dict) -> list[dict]:
    """Flatten a Transit ``alerts_for_networks`` payload to plain dicts.

    Tolerates the top-level ``{"alerts": [...]}`` shape and the nested
    ``{"networks": [{"alerts": [...]}, ...]}`` shape, and several field
    spellings, so an upstream payload tweak degrades to fewer fields
    rather than an exception.
    """
    raw: list = []
    top = payload.get("alerts")
    if isinstance(top, list):
        raw = list(top)
    else:
        for net in payload.get("networks") or []:
            if isinstance(net, dict) and isinstance(net.get("alerts"), list):
                raw.extend(net["alerts"])
    out: list[dict] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        out.append({
            "id": a.get("alert_id") or a.get("id") or a.get("global_alert_id"),
            "title": a.get("title") or a.get("header_text") or a.get("header"),
            "description": a.get("description") or a.get("description_text"),
            "severity": a.get("severity") or a.get("severity_level"),
            "effect": a.get("effect"),
            "url": a.get("url") or a.get("alert_url"),
        })
    return out


def fetch_sorta_alerts(
    *,
    network_id: str | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """Normalized SORTA service alerts, or ``[]`` when unavailable.

    Resolves SORTA's network id (or uses the explicit ``network_id``
    override), calls ``alerts_for_networks``, and flattens the payload
    to ``{"id", "title", "description", "severity", "effect", "url"}``
    dicts via :func:`_normalize_alerts`. Fail-open: no key, quota
    exhausted, no SORTA match, or a malformed payload all yield ``[]``.
    """
    nid = network_id or resolve_sorta_network_id(force_refresh=force_refresh)
    if not nid:
        return []
    payload = alerts_for_networks([nid], force_refresh=force_refresh)
    if not payload:
        return []
    return _normalize_alerts(payload)


__all__ = [
    "AUTH_HEADER",
    "CACHE_DIR",
    "KEY_FILE",
    "MONTHLY_QUOTA_FREE_TIER",
    "POWERED_BY_TRANSIT_ATTRIBUTION",
    "QUOTA_BUDGET_FRACTION",
    "RATE_LIMIT_PER_MINUTE",
    "SORTA_NETWORK_HINTS",
    "TRANSIT_BASE_URL",
    "TTL_BY_ENDPOINT",
    "USAGE_FILE",
    "USER_AGENT",
    "TransitClientStatus",
    "alerts_for_networks",
    "available_networks",
    "cross_check_bus_stop_findings",
    "fetch_sorta_alerts",
    "nearby_stops",
    "resolve_sorta_network_id",
    "status",
    "stop_departures",
    "trip_plan",
]
