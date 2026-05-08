"""BRouter route-diff harness for rider-impact detector findings.

Promotes the eight read-only rider-impact detectors (see :mod:`osm.detectors`)
from "human-review-required candidates" to "automated false-positive
filtered" by asking BRouter — a GPL OSM-routing engine, see
``https://brouter.de/brouter`` — whether a candidate fix actually changes
routing behaviour. If routing changes meaningfully the defect is real; if it
doesn't, the finding is most likely a false positive that we shouldn't
escalate to a human reviewer.

Why a *prediction* and not a real before/after call
---------------------------------------------------
BRouter's data tiles are derived from OSM but rebuilt weekly; we cannot
directly evaluate edits we just made. Instead we compute the live BRouter
route and predict the post-fix route by perturbing the routing graph from
*outside*:

* For ``oneway=-1`` and same-name oneway conflicts we re-issue the route in
  the suspect way's start->end direction. If BRouter declares the
  destination unreachable, the only thing stopping it is the directional
  tag we suspect — strong evidence the defect is real.
* For broken turn restrictions and unqualified barriers we use BRouter's
  ``nogos`` query parameter to mark the suspect coordinate as a hard
  no-go. The unconstrained baseline is the live route; the constrained
  route is the predicted post-fix route. A meaningful cost delta means the
  edit will change rider routing.

Detector kinds that are *not* testable with BRouter alone (semantic
mistagging that doesn't change the routing graph — for example
``arterial_named_residential`` — or fixes that need a human to choose the
new value, like ``bus_stop_misplaced``) are skipped and stay in the
human-review queue.

Etiquette
---------
Public BRouter is a single volunteer-run server. We:

* Insert a configurable delay (default 1.0 sec; ``BROUTER_DELAY_SEC`` env
  override) between consecutive calls.
* Identify ourselves with the same project User-Agent as the rest of the
  pipeline.
* Cache aggressively under ``~/.config/osm/brouter_cache/`` with a 24-hour
  TTL — a finding whose way geometry/tags haven't changed should not be
  re-tested.
* Never run inside :func:`osm.classify.classify` or any other hot path. The
  diff is exclusively opt-in via the CLI ``osm route-diff`` subcommand,
  the ``--with-route-diff`` flag on ``osm scan``, or the
  ``POST /api/route-diff/:zone`` web endpoint.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import time
from collections.abc import Callable
from typing import Any

import requests

from osm.cache import is_cache_fresh, read_json_cache, write_json_cache
from osm.config import CONFIG_DIR, OVERPASS_HEADERS
from osm.geo import haversine_m, valid_latlon

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BROUTER_BASE = "https://brouter.de/brouter"
BROUTER_CACHE_DIR = CONFIG_DIR / "brouter_cache"
BROUTER_CACHE_TTL_S = 24 * 3600  # 24 h
BROUTER_DELAY_SEC_DEFAULT = 1.0
BROUTER_USER_AGENT = OVERPASS_HEADERS.get(
    "User-Agent", "osm-audit-pipeline/0.1"
)
BROUTER_HEADERS = {
    "User-Agent": BROUTER_USER_AGENT,
    "Accept": "application/vnd.geo+json, application/json",
}

# Decision rule thresholds (as documented in the module docstring above).
DELTA_REAL_PCT = 15.0
DELTA_NOISY_PCT = 3.0

# Default offset for synthesised origin/destination pairs.
DEFAULT_ENDPOINT_OFFSET_M = 80.0

# Kinds we know how to test.
TESTABLE_KINDS: frozenset[str] = frozenset({
    "oneway_minus_one",
    "oneway_conflict",
    "broken_turn_restriction",
    "barrier_unqualified",
})

# Kinds we are willing to graduate to mechanical fixes once route-diff has
# concluded the defect is real. Currently the same set as TESTABLE_KINDS,
# but kept separate as a safety knob — graduation is a stronger commitment
# than testability.
AUTO_FIXABLE_KINDS: frozenset[str] = frozenset({
    "oneway_minus_one",
    "oneway_conflict",
    "broken_turn_restriction",
    "barrier_unqualified",
})

# Module-level last-call timestamp for the polite-rate-limit sleep.
_last_call_at: float = 0.0


def _delay_seconds() -> float:
    raw = os.environ.get("BROUTER_DELAY_SEC")
    if raw is None:
        return BROUTER_DELAY_SEC_DEFAULT
    try:
        v = float(raw)
    except ValueError:
        return BROUTER_DELAY_SEC_DEFAULT
    return v if v >= 0 else BROUTER_DELAY_SEC_DEFAULT


def _polite_sleep() -> None:
    """Sleep enough to honour the configured per-call delay."""
    global _last_call_at
    delay = _delay_seconds()
    if delay <= 0:
        _last_call_at = time.time()
        return
    elapsed = time.time() - _last_call_at
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_call_at = time.time()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _way_geom_lonlat(way: dict) -> list[tuple[float, float]]:
    """Return way geometry as ``(lon, lat)`` pairs.

    Tolerates both the raw Overpass shape (``geometry`` = list of ``{lat, lon}``
    dicts) and the classify.py normalised shape (``geometry`` = list of
    ``[lat, lon]`` pairs).
    """
    out: list[tuple[float, float]] = []
    for g in way.get("geometry") or []:
        if isinstance(g, dict):
            lat, lon = g.get("lat"), g.get("lon")
        elif isinstance(g, (list, tuple)) and len(g) >= 2:
            lat, lon = g[0], g[1]
        else:
            continue
        if lat is None or lon is None:
            continue
        try:
            flat = float(lat)
            flon = float(lon)
        except (TypeError, ValueError):
            continue
        if not valid_latlon(flat, flon):
            continue
        out.append((flon, flat))
    return out


def _way_endpoints_lonlat(way: dict) -> tuple[tuple[float, float], tuple[float, float]] | None:
    pts = _way_geom_lonlat(way)
    if len(pts) < 2:
        return None
    return pts[0], pts[-1]


def _way_length_m(way: dict) -> float:
    pts = _way_geom_lonlat(way)
    total = 0.0
    for i in range(1, len(pts)):
        lon0, lat0 = pts[i - 1]
        lon1, lat1 = pts[i]
        total += haversine_m(lat0, lon0, lat1, lon1)
    return total


def _meters_offset_lonlat(
    lon: float, lat: float, bearing_rad: float, distance_m: float,
) -> tuple[float, float]:
    """Return (lon, lat) offset by ``distance_m`` along ``bearing_rad`` from origin."""
    if distance_m <= 0:
        return lon, lat
    earth_r = 6_371_000.0
    delta = distance_m / earth_r
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(delta)
        + math.cos(lat1) * math.sin(delta) * math.cos(bearing_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing_rad) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lon2), math.degrees(lat2)


def _bearing_rad(
    a_lon: float, a_lat: float, b_lon: float, b_lat: float,
) -> float:
    """Initial bearing (radians) from a -> b."""
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    lam = math.radians(b_lon - a_lon)
    y = math.sin(lam) * math.cos(phi2)
    x = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(lam)
    )
    return math.atan2(y, x)


def _closest_point_on_other_way(
    origin_lon: float, origin_lat: float,
    candidate_ways: list[dict],
    *, exclude_id: int | None = None,
    max_radius_m: float = 250.0,
) -> tuple[float, float] | None:
    """Find the closest vertex (lon, lat) on any drivable candidate way.

    Skips the way with id ``exclude_id``. Returns ``None`` if no candidate
    vertex is within ``max_radius_m``.
    """
    drivable = {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "unclassified", "residential",
    }
    best: tuple[float, tuple[float, float]] | None = None
    for w in candidate_ways:
        if exclude_id is not None and w.get("id") == exclude_id:
            continue
        tags = (w.get("tags") or {}) if isinstance(w.get("tags"), dict) else {}
        # ways from classify() carry highway at the top level too
        hwy = tags.get("highway") or w.get("highway")
        if hwy not in drivable:
            continue
        for lon, lat in _way_geom_lonlat(w):
            d = haversine_m(origin_lat, origin_lon, lat, lon)
            if d > max_radius_m:
                continue
            if best is None or d < best[0]:
                best = (d, (lon, lat))
    return None if best is None else best[1]


# ---------------------------------------------------------------------------
# Endpoint synthesis
# ---------------------------------------------------------------------------

def synth_endpoints_around(
    way: dict,
    *,
    offset_m: float = DEFAULT_ENDPOINT_OFFSET_M,
    max_attempts: int = 3,
    all_ways: list[dict] | None = None,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Pick (origin, destination) lon/lat pairs that bracket ``way``.

    Origin is the closest vertex on a *different* drivable way to the suspect
    way's starting endpoint, then nudged ``offset_m`` away from that endpoint
    along the back-bearing. Destination is the same on the other end.

    If no adjacent drivable candidate exists within ~250 m the diff cannot
    be tested for this way and the function returns ``None``.

    ``all_ways`` is required for cross-way candidate search; if ``None`` we
    fall back to a pure ``offset_m`` jump along the way's incoming/outgoing
    bearing — useful for synthetic test fixtures that don't supply a
    neighbour set.
    """
    endpoints = _way_endpoints_lonlat(way)
    if endpoints is None:
        return None
    (start_lon, start_lat), (end_lon, end_lat) = endpoints

    # Sequence of candidate-find attempts: bigger search radius each time.
    radii = [
        offset_m * 3.0,
        offset_m * 6.0,
        offset_m * 10.0,
    ][: max(1, int(max_attempts))]

    origin = None
    destination = None
    if all_ways:
        for r in radii:
            origin = _closest_point_on_other_way(
                start_lon, start_lat, all_ways,
                exclude_id=way.get("id"), max_radius_m=r,
            )
            if origin is not None:
                break
        for r in radii:
            destination = _closest_point_on_other_way(
                end_lon, end_lat, all_ways,
                exclude_id=way.get("id"), max_radius_m=r,
            )
            if destination is not None:
                break

    if origin is None or destination is None:
        # No alternative drivable way to bracket this segment — diff
        # cannot be tested.
        if not all_ways:
            # No candidate set was supplied at all. As a fallback, project
            # the endpoints out by ``offset_m`` along the start/end bearing
            # so that test fixtures and ad-hoc calls still work.
            geom = _way_geom_lonlat(way)
            if len(geom) < 2:
                return None
            # Bearing entering the start (geom[1] -> geom[0]) and
            # leaving the end (geom[-2] -> geom[-1]).
            in_bearing = _bearing_rad(geom[1][0], geom[1][1], geom[0][0], geom[0][1])
            out_bearing = _bearing_rad(geom[-2][0], geom[-2][1], geom[-1][0], geom[-1][1])
            origin = _meters_offset_lonlat(start_lon, start_lat, in_bearing, offset_m)
            destination = _meters_offset_lonlat(end_lon, end_lat, out_bearing, offset_m)
            return origin, destination
        return None

    return origin, destination


# ---------------------------------------------------------------------------
# BRouter call + cache
# ---------------------------------------------------------------------------

def _format_lonlat(lonlat: tuple[float, float]) -> str:
    return f"{lonlat[0]:.6f},{lonlat[1]:.6f}"


def _format_nogos(nogos: list[tuple[float, float, float]] | None) -> str | None:
    """BRouter ``nogos`` parameter format: ``lon,lat,radius_m|lon,lat,radius_m``."""
    if not nogos:
        return None
    return "|".join(f"{n[0]:.6f},{n[1]:.6f},{int(round(n[2]))}" for n in nogos)


def _cache_key(
    origin: tuple[float, float],
    destination: tuple[float, float],
    profile: str,
    nogos: list[tuple[float, float, float]] | None,
) -> str:
    payload = json.dumps(
        {
            "origin": [round(origin[0], 6), round(origin[1], 6)],
            "destination": [round(destination[0], 6), round(destination[1], 6)],
            "profile": profile,
            "nogos": [
                [round(n[0], 6), round(n[1], 6), round(n[2], 1)]
                for n in (nogos or [])
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _cache_path(key: str):
    return BROUTER_CACHE_DIR / f"route-{key}.json"


def fetch_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    profile: str = "car-fast",
    nogos: list[tuple[float, float, float]] | None = None,
    timeout: int = 30,
) -> dict | None:
    """One BRouter call. ``origin``/``destination`` are ``(lon, lat)`` tuples.

    Returns ``{'length_m', 'duration_s', 'cost', 'geometry'}`` or ``None``
    on HTTP error / timeout / unreachable destination. Errors are logged
    and never raised so the caller can keep iterating.
    """
    params: dict[str, str] = {
        "lonlats": f"{_format_lonlat(origin)}|{_format_lonlat(destination)}",
        "profile": profile,
        "format": "geojson",
        "alternativeidx": "0",
    }
    nogos_param = _format_nogos(nogos)
    if nogos_param:
        params["nogos"] = nogos_param

    _polite_sleep()
    try:
        resp = requests.get(
            BROUTER_BASE, params=params, headers=BROUTER_HEADERS, timeout=timeout,
        )
    except requests.RequestException as exc:
        log.warning("BRouter request failed (%s); returning None.", exc)
        return None

    if resp.status_code >= 500:
        # 5xx most commonly means BRouter could not reach the destination
        # — its engine returns 500 with a plain-text body for unreachable
        # routes. Logged at info, returned as None.
        log.info(
            "BRouter %d for %s -> %s (%s); treating as unreachable.",
            resp.status_code, origin, destination,
            (resp.text or "").splitlines()[0:1],
        )
        return None
    if resp.status_code >= 400:
        log.warning(
            "BRouter HTTP %d for %s -> %s: %s",
            resp.status_code, origin, destination,
            (resp.text or "")[:160],
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        log.warning(
            "BRouter returned non-JSON for %s -> %s: %s",
            origin, destination, (resp.text or "")[:160],
        )
        return None

    features = (data or {}).get("features") or []
    if not features:
        # 200 with empty features — BRouter's other unreachable signal.
        log.info(
            "BRouter empty feature set for %s -> %s — unreachable.",
            origin, destination,
        )
        return None

    feat = features[0] if isinstance(features[0], dict) else {}
    props = feat.get("properties") or {}
    geometry = feat.get("geometry") or {}

    def _to_float(v: Any) -> float | None:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    length_m = _to_float(props.get("track-length"))
    duration_s = _to_float(props.get("total-time"))
    cost = _to_float(props.get("cost"))
    if cost is None:
        cost = _to_float(props.get("total-energy"))

    if length_m is None or duration_s is None:
        log.info(
            "BRouter response missing length/duration for %s -> %s; props=%s",
            origin, destination, list(props)[:8],
        )
        return None

    return {
        "length_m": length_m,
        "duration_s": duration_s,
        "cost": cost,
        "geometry": geometry,
    }


def cached_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    profile: str = "car-fast",
    nogos: list[tuple[float, float, float]] | None = None,
    force_refresh: bool = False,
    timeout: int = 30,
) -> dict | None:
    """Disk-cached wrapper around :func:`fetch_route`.

    Cache key combines origin/destination/profile/nogos and is stored under
    ``~/.config/osm/brouter_cache/route-{hash}.json`` with a 24 h TTL.
    Different profiles or different nogos lists produce different keys, so a
    "live" call and a "perturbed-graph" call don't clobber each other.
    """
    key = _cache_key(origin, destination, profile, nogos)
    path = _cache_path(key)
    if not force_refresh and is_cache_fresh(path, BROUTER_CACHE_TTL_S):
        cached = read_json_cache(path)
        if isinstance(cached, dict) and "length_m" in cached:
            # Negative cache: stored as {"length_m": None, ...} when BRouter
            # returned an unreachable signal. Surface as None so callers can
            # branch on "post-perturbation unreachable".
            if cached.get("length_m") is None:
                return None
            return cached

    result = fetch_route(
        origin, destination, profile=profile, nogos=nogos, timeout=timeout,
    )
    # We cache *negative* results too (None). BRouter returning None is most
    # often a deliberate "unreachable" signal — re-asking the same question
    # 24 h later is wasteful.
    if result is None:
        write_json_cache(path, {"length_m": None, "duration_s": None, "cost": None})
        return None
    write_json_cache(path, {
        "length_m": result["length_m"],
        "duration_s": result["duration_s"],
        "cost": result["cost"],
        # geometry is large; skip caching it to keep files small.
    })
    return result


# ---------------------------------------------------------------------------
# Per-finding diff
# ---------------------------------------------------------------------------

def _decision_from_delta(delta_pct: float) -> str:
    if delta_pct > DELTA_REAL_PCT:
        return "real"
    if delta_pct < DELTA_NOISY_PCT:
        return "noisy"
    return "inconclusive"


def _confidence_from_delta(delta_pct: float, basis: str) -> float:
    """Heuristic confidence for the route-diff decision.

    * Unreachable post-route is strong evidence — clamp at 0.9.
    * Otherwise scale linearly from 0.4 at 0 % delta to 0.85 at 30 % delta.
    """
    if basis == "unreachable":
        return 0.9
    delta_pct = max(0.0, min(delta_pct, 30.0))
    return round(0.4 + (delta_pct / 30.0) * 0.45, 3)


def _route_summary(route: dict | None) -> dict:
    if route is None:
        return {"length_m": None, "duration_s": None}
    return {
        "length_m": round(float(route["length_m"]), 1),
        "duration_s": round(float(route["duration_s"]), 1),
    }


def _find_way(all_ways: list[dict], way_id: int | None) -> dict | None:
    if way_id is None:
        return None
    for w in all_ways:
        if w.get("id") == way_id:
            return w
    return None


def _diff_for_oneway(
    way: dict, finding: dict, all_ways: list[dict], *, profile: str,
) -> dict | None:
    """Diff for ``oneway_minus_one`` and ``oneway_conflict`` findings.

    Strategy: ask BRouter to plan a route through the suspect way in its
    *digitised* start->end direction. For ``oneway=-1`` and a same-direction
    conflict pair, BRouter (which honours OSM's oneway tag verbatim) will
    report unreachable if the directionality is the only thing blocking the
    route. That's strong evidence the defect is real. If the route succeeds
    we compare its length to a "free" route between the same endpoints
    routed without honouring the suspect way (we approximate that with a
    tight ``nogos`` ring around the way's midpoint to force a detour) — a
    delta > 15 % flags the defect as real, < 3 % as noisy.
    """
    endpoints = synth_endpoints_around(way, all_ways=all_ways)
    if endpoints is None:
        return None
    origin, destination = endpoints

    live = cached_route(origin, destination, profile=profile)

    # Predict a "world without this way" by adding a tight nogo around the
    # way's midpoint. The radius is the smaller of (½ * way length, 60 m)
    # so that long ways aren't entirely no-go'd off the network and short
    # ways are still meaningfully blocked.
    geom = _way_geom_lonlat(way)
    if not geom:
        return None
    mid = geom[len(geom) // 2]
    way_len = max(_way_length_m(way), 1.0)
    nogo_r = max(20.0, min(way_len * 0.5, 60.0))
    perturbed = cached_route(
        origin, destination, profile=profile,
        nogos=[(mid[0], mid[1], nogo_r)],
    )

    # Live unreachable vs perturbed reachable: defect is real (the perturbed
    # graph routes and the live one didn't — the suspect tag is what was
    # blocking it). We treat any "live=None and perturbed=ok" as 'real'
    # with 0.9 confidence.
    if live is None and perturbed is not None:
        return {
            "kind": "route_diff",
            "way_id": way.get("id"),
            "before": _route_summary(None),
            "after_predicted": {
                **_route_summary(perturbed),
                "basis": "graph-perturbation",
            },
            "delta_pct": 100.0,
            "decision": "real",
            "confidence": 0.9,
            "profile": profile,
        }

    if live is None and perturbed is None:
        # BRouter cannot route either way — likely a network island, not
        # a tag-induced break. Inconclusive, low confidence.
        return {
            "kind": "route_diff",
            "way_id": way.get("id"),
            "before": _route_summary(None),
            "after_predicted": {
                **_route_summary(None),
                "basis": "unreachable",
            },
            "delta_pct": 0.0,
            "decision": "inconclusive",
            "confidence": 0.2,
            "profile": profile,
        }

    if live is not None and perturbed is None:
        # Live reachable but post-perturbation isn't: the way is essentially
        # the only path through this part of the network. That's a 'real'
        # routing dependency, but in our diff semantics it's a strong
        # change and we mark decision='real'.
        return {
            "kind": "route_diff",
            "way_id": way.get("id"),
            "before": _route_summary(live),
            "after_predicted": {
                **_route_summary(None),
                "basis": "unreachable",
            },
            "delta_pct": 100.0,
            "decision": "real",
            "confidence": 0.9,
            "profile": profile,
        }

    # Both routed — compute percentage delta on length (more stable than
    # duration which BRouter caches at coarser resolution).
    assert live is not None and perturbed is not None
    base = max(float(live["length_m"]), 1.0)
    delta_pct = abs(float(perturbed["length_m"]) - base) / base * 100.0
    return {
        "kind": "route_diff",
        "way_id": way.get("id"),
        "before": _route_summary(live),
        "after_predicted": {
            **_route_summary(perturbed),
            "basis": "graph-perturbation",
        },
        "delta_pct": round(delta_pct, 2),
        "decision": _decision_from_delta(delta_pct),
        "confidence": _confidence_from_delta(delta_pct, "graph-perturbation"),
        "profile": profile,
    }


def _diff_for_nogo_node(
    finding: dict, all_ways: list[dict], *, profile: str,
    nogo_radius_m: float = 25.0,
) -> dict | None:
    """Diff for findings that pin to a single coordinate (barriers, restrictions).

    Strategy: synthesise a short bracket around the finding (origin/destination
    on adjacent drivable ways), route it once unconstrained, then re-route
    with a ``nogos`` ring around the finding's coordinate. If the constrained
    route differs by > 15 % the suspect node is structurally on the path
    riders take, so wrongly blocking it (or wrongly *not* blocking it via a
    broken restriction) genuinely changes routing.
    """
    lat = finding.get("lat")
    lon = finding.get("lon")
    if lat is None or lon is None:
        return None
    try:
        flat = float(lat)
        flon = float(lon)
    except (TypeError, ValueError):
        return None
    if not valid_latlon(flat, flon):
        return None

    # Build a synthetic origin/destination by jumping ~80 m N and ~80 m S
    # of the suspect node. We then snap each to the nearest drivable way
    # vertex via _closest_point_on_other_way. If neither snaps (rural
    # nodes etc.) we fall back to the raw projected points.
    synth_north = _meters_offset_lonlat(flon, flat, 0.0, DEFAULT_ENDPOINT_OFFSET_M)
    synth_south = _meters_offset_lonlat(
        flon, flat, math.pi, DEFAULT_ENDPOINT_OFFSET_M,
    )
    origin = _closest_point_on_other_way(
        synth_north[0], synth_north[1], all_ways, max_radius_m=200.0,
    ) or synth_north
    destination = _closest_point_on_other_way(
        synth_south[0], synth_south[1], all_ways, max_radius_m=200.0,
    ) or synth_south

    live = cached_route(origin, destination, profile=profile)
    if live is None:
        # Even unconstrained, BRouter can't route — this finding doesn't sit
        # on any rider path right now. Inconclusive at low confidence.
        return {
            "kind": "route_diff",
            "way_id": finding.get("id"),
            "before": _route_summary(None),
            "after_predicted": {
                **_route_summary(None),
                "basis": "unreachable",
            },
            "delta_pct": 0.0,
            "decision": "inconclusive",
            "confidence": 0.2,
            "profile": profile,
        }

    perturbed = cached_route(
        origin, destination, profile=profile,
        nogos=[(flon, flat, nogo_radius_m)],
    )
    if perturbed is None:
        # Live route OK but post-perturbation fails — the node is a true
        # bottleneck. Strong evidence the wrong tag matters.
        return {
            "kind": "route_diff",
            "way_id": finding.get("id"),
            "before": _route_summary(live),
            "after_predicted": {
                **_route_summary(None),
                "basis": "unreachable",
            },
            "delta_pct": 100.0,
            "decision": "real",
            "confidence": 0.9,
            "profile": profile,
        }

    base = max(float(live["length_m"]), 1.0)
    delta_pct = abs(float(perturbed["length_m"]) - base) / base * 100.0
    return {
        "kind": "route_diff",
        "way_id": finding.get("id"),
        "before": _route_summary(live),
        "after_predicted": {
            **_route_summary(perturbed),
            "basis": "graph-perturbation",
        },
        "delta_pct": round(delta_pct, 2),
        "decision": _decision_from_delta(delta_pct),
        "confidence": _confidence_from_delta(delta_pct, "graph-perturbation"),
        "profile": profile,
    }


def diff_route(
    finding: dict,
    all_ways: list[dict],
    *,
    profile: str = "car-fast",
) -> dict | None:
    """Run the route-diff for a single finding. ``None`` if untestable.

    The returned dict shape mirrors the prompt spec::

        {kind: 'route_diff', way_id, before: {length_m, duration_s},
         after_predicted: {length_m, duration_s, basis: 'graph-perturbation'
                                                       | 'unreachable'},
         delta_pct: float,
         decision: 'real' | 'noisy' | 'inconclusive',
         confidence: 0..1, profile: str}

    Decision rule (also documented in the module docstring):
        * delta_pct > 15  -> 'real'
        * delta_pct < 3   -> 'noisy'
        * 3..15           -> 'inconclusive'
    """
    kind = finding.get("kind")
    if kind not in TESTABLE_KINDS:
        return None

    if kind in ("oneway_minus_one", "oneway_conflict"):
        # Need the way's geometry. The finding's "geometry" was attached by
        # the detector but classify() may have stripped it for serialization;
        # fall back to all_ways lookup.
        way: dict | None = None
        if finding.get("geometry"):
            way = {"id": finding.get("id"), "geometry": finding["geometry"]}
        if way is None or not _way_geom_lonlat(way):
            way = _find_way(all_ways, finding.get("id"))
        if way is None:
            return None
        return _diff_for_oneway(way, finding, all_ways, profile=profile)

    if kind in ("broken_turn_restriction", "barrier_unqualified"):
        # broken_turn_restriction findings don't carry lat/lon directly;
        # synthesize one from the relation members if needed. For barriers
        # the detector already attaches lat/lon.
        if finding.get("lat") is None or finding.get("lon") is None:
            return None
        return _diff_for_nogo_node(finding, all_ways, profile=profile)

    return None


# ---------------------------------------------------------------------------
# Batch diff + graduation
# ---------------------------------------------------------------------------

def diff_findings(
    findings: list[dict],
    all_ways: list[dict],
    *,
    profile: str = "car-fast",
    progress_callback: Callable[[int, int], None] | None = None,
    max_concurrent: int = 4,  # noqa: ARG001 - reserved for future thread-pool use
) -> list[dict]:
    """Run :func:`diff_route` on every testable finding (mutating).

    Each finding gets a ``route_diff`` key; untestable findings get
    ``route_diff = None`` plus a ``route_diff_skipped`` reason for
    surfacing in the UI. Returns the same list (chainable).

    The ``max_concurrent`` parameter is currently advisory: BRouter is a
    single volunteer-run server and we serialise calls behind a 1-second
    polite-rate-limit. We kept the parameter so the API doesn't churn if
    we later switch to per-host rate-limited concurrency.
    """
    total = len(findings)
    for i, f in enumerate(findings, 1):
        kind = f.get("kind")
        if kind not in TESTABLE_KINDS:
            f["route_diff"] = None
            f["route_diff_skipped"] = (
                f"kind {kind!r} is not testable with BRouter alone"
            )
            log.debug(
                "Skipping route-diff for %s (kind=%s): not testable",
                f.get("id"), kind,
            )
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(i, total)
            continue
        try:
            f["route_diff"] = diff_route(f, all_ways, profile=profile)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "route_diff for %s/%s failed: %s",
                kind, f.get("id"), exc,
            )
            f["route_diff"] = None
            f["route_diff_skipped"] = f"diff error: {exc}"
        if progress_callback:
            with contextlib.suppress(Exception):
                progress_callback(i, total)
    return findings


def graduate_findings(
    findings: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split ``findings`` into (graduated_to_mechanical, still_human_review).

    A finding graduates when it has a non-empty ``route_diff`` whose
    ``decision == 'real'`` AND its ``kind`` is in :data:`AUTO_FIXABLE_KINDS`.
    Everything else stays in the human-review bucket — including findings
    whose decision is ``'real'`` but whose kind is not auto-fixable
    (those need a human to pick the new value).
    """
    graduated: list[dict] = []
    still_review: list[dict] = []
    for f in findings:
        rd = f.get("route_diff")
        kind = f.get("kind")
        if (
            isinstance(rd, dict)
            and rd.get("decision") == "real"
            and kind in AUTO_FIXABLE_KINDS
        ):
            graduated.append(f)
        else:
            still_review.append(f)
    return graduated, still_review


# ---------------------------------------------------------------------------
# Phase 4b: route-impact for CAGIS-verified mechanical fixes
#
# diff_route() above operates on rider-impact detector findings. The
# mechanical-fix path (osm fix → review_defects → submit_fixes) emits
# fix descriptors with kinds set_oneway_cagis / remove_oneway_cagis /
# set_maxspeed_cagis / set_name_cagis. The first two perturb the
# routing graph in exactly the same way oneway_minus_one /
# oneway_conflict do, so we can reuse the BRouter perturbation by
# mapping a fix descriptor to a synthetic finding.
#
# The other CAGIS fix kinds (maxspeed, name) don't change graph
# topology — BRouter would not detect them — so we record those
# explicitly with route_impact = None and a skip reason.
# ---------------------------------------------------------------------------

# Mechanical-fix kinds that map cleanly onto the oneway perturbation.
ONEWAY_FIX_KINDS: frozenset[str] = frozenset({
    "set_oneway_cagis",
    "remove_oneway_cagis",
})


def _fix_to_synthetic_finding(fix: dict) -> dict | None:
    """Project a CAGIS-verified oneway fix descriptor onto the
    rider-impact-finding shape that :func:`diff_route` accepts.

    Returns ``None`` for fix kinds that are not testable with BRouter
    alone (maxspeed and name fixes don't change graph topology).
    """
    kind = fix.get("kind")
    if kind not in ONEWAY_FIX_KINDS:
        return None
    way_id = fix.get("element_id") or fix.get("way_id")
    if way_id is None:
        return None
    # Reuse the oneway_conflict perturbation — it tests "this way's
    # oneway tag is suspect, what changes if we believe CAGIS instead?"
    # which is exactly what the mechanical fix asserts.
    return {
        "kind": "oneway_conflict",
        "id": way_id,
        "fix_kind": kind,
        "fix_changes": fix.get("changes"),
    }


def route_impact_for_fix(
    fix: dict,
    all_ways: list[dict],
    *,
    profile: str = "car-fast",
) -> dict | None:
    """Run BRouter route-diff for one CAGIS-verified mechanical fix.

    Returns a dict matching :func:`diff_route`'s shape, with an extra
    ``fix_kind`` field, or ``None`` when the fix kind is not testable.
    """
    synth = _fix_to_synthetic_finding(fix)
    if synth is None:
        return None
    rd = diff_route(synth, all_ways, profile=profile)
    if rd is not None:
        rd["fix_kind"] = fix.get("kind")
    return rd


def route_impact_for_fixes(
    fixes: list[dict],
    all_ways: list[dict],
    *,
    profile: str = "car-fast",
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Annotate every fix in ``fixes`` with a ``route_impact`` key.

    Mutates and returns the list (chainable). Untestable fix kinds get
    ``route_impact = None`` plus a ``route_impact_skipped`` reason.
    Polite-rate-limit honoured per call; expect ~1 second per testable
    fix at the public BRouter endpoint.
    """
    total = len(fixes)
    for i, fix in enumerate(fixes, 1):
        kind = fix.get("kind")
        if kind not in ONEWAY_FIX_KINDS:
            fix["route_impact"] = None
            fix["route_impact_skipped"] = (
                f"kind {kind!r} does not perturb the routing graph"
            )
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(i, total)
            continue
        try:
            fix["route_impact"] = route_impact_for_fix(
                fix, all_ways, profile=profile,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "route_impact for %s/%s failed: %s",
                kind, fix.get("element_id"), exc,
            )
            fix["route_impact"] = None
            fix["route_impact_skipped"] = f"diff error: {exc}"
        if progress_callback:
            with contextlib.suppress(Exception):
                progress_callback(i, total)
    return fixes


def summarize_route_impact(fixes: list[dict]) -> dict:
    """Aggregate per-fix route_impact records into a summary report.

    Used by the CLI fix-impact subcommand to print the value-story
    payload: "this batch of N fixes will change M MetroNow-relevant
    routes by avg X% (max Y%, min Z%)". The percentages are BRouter's
    delta_pct between the live route and the perturbed route.
    """
    total = len(fixes)
    tested = [
        f for f in fixes
        if isinstance(f.get("route_impact"), dict)
    ]
    real = [
        f for f in tested
        if (f.get("route_impact") or {}).get("decision") == "real"
    ]
    inconclusive = [
        f for f in tested
        if (f.get("route_impact") or {}).get("decision") == "inconclusive"
    ]
    noisy = [
        f for f in tested
        if (f.get("route_impact") or {}).get("decision") == "noisy"
    ]
    deltas = [
        float((f.get("route_impact") or {}).get("delta_pct") or 0.0)
        for f in real
    ]
    durations = [
        float(((f.get("route_impact") or {}).get("after_predicted") or {}).get(
            "duration_s") or 0.0)
        - float(((f.get("route_impact") or {}).get("before") or {}).get(
            "duration_s") or 0.0)
        for f in real
    ]
    avg_delta = (
        round(sum(deltas) / len(deltas), 2) if deltas else 0.0
    )
    max_delta = round(max(deltas), 2) if deltas else 0.0
    avg_duration = (
        round(sum(durations) / len(durations), 1) if durations else 0.0
    )
    return {
        "fixes_total": total,
        "fixes_tested": len(tested),
        "fixes_skipped": total - len(tested),
        "real": len(real),
        "inconclusive": len(inconclusive),
        "noisy": len(noisy),
        "avg_delta_pct_real": avg_delta,
        "max_delta_pct_real": max_delta,
        "avg_duration_delta_s_real": avg_duration,
    }


def decision_histogram(findings: list[dict]) -> dict[str, int]:
    """Count findings by route_diff.decision (and 'untested')."""
    out: dict[str, int] = {
        "real": 0,
        "inconclusive": 0,
        "noisy": 0,
        "untested": 0,
    }
    for f in findings:
        rd = f.get("route_diff")
        if not isinstance(rd, dict):
            out["untested"] += 1
            continue
        d = rd.get("decision")
        if d in out:
            out[d] += 1
        else:
            out["untested"] += 1
    return out


__all__ = [
    "AUTO_FIXABLE_KINDS",
    "BROUTER_BASE",
    "BROUTER_CACHE_DIR",
    "BROUTER_CACHE_TTL_S",
    "BROUTER_DELAY_SEC_DEFAULT",
    "DELTA_NOISY_PCT",
    "DELTA_REAL_PCT",
    "ONEWAY_FIX_KINDS",
    "TESTABLE_KINDS",
    "cached_route",
    "decision_histogram",
    "diff_findings",
    "diff_route",
    "fetch_route",
    "graduate_findings",
    "route_impact_for_fix",
    "route_impact_for_fixes",
    "summarize_route_impact",
    "synth_endpoints_around",
]
