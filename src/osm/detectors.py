"""Rider-impact defect detectors.

These run alongside the existing Class A/B/AB/C classifier (see
``osm.classify``). Each detector takes a normalised collection of OSM
elements and returns a list of finding dicts with at least:

    - ``kind``:           short stable identifier (e.g. ``"oneway_minus_one"``)
    - ``id``:             OSM element id (way / node / relation)
    - ``name``:           ``name`` tag, if any
    - ``severity``:       ``CRITICAL`` / ``HIGH`` / ``MEDIUM`` / ``LOW``
    - ``description``:    short human-readable line
    - ``routing_impact``: 1..5 (5 = blocks an arterial-class route)
    - ``geometry`` / ``lat`` / ``lon`` (where applicable)

Detectors are deliberately independent so a single broken one cannot
take down a whole audit run; the caller wraps each in try/except.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from .classify import CLASS_A_HIGHWAYS, ONEWAY_TRUTHY, is_oneway_truthy
from .config import CRITICAL, HIGH, LOW
from .geo import haversine_m, valid_latlon

log = logging.getLogger(__name__)

# A separate "MEDIUM" severity for findings that aren't critical but are
# noisier than the LOW residual class. Kept local — config.py only models
# the three legacy levels and we don't want to widen that public surface.
MEDIUM = "MEDIUM"

# Drivable highway tags used for bus-stop snapping & arterial detectors.
DRIVABLE_HIGHWAYS = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service",
})

ARTERIAL_HIGHWAYS = frozenset({
    "tertiary", "unclassified", "secondary", "primary", "trunk",
})

# Tighter set used by ``detect_missing_maxspeed_arterial``: secondary/primary/
# trunk usually omit ``maxspeed`` legitimately (signage tells the driver) and
# aren't where class-default speed inference goes most wrong. Tertiary and
# unclassified are where ViaAlgo-style routers most often pick the wrong
# default speed and hurt rider ETAs.
MISSING_MAXSPEED_HIGHWAYS = frozenset({"tertiary", "unclassified"})

ACCESS_BLOCKED_VALUES = frozenset({"no", "private"})

QUALIFIED_BARRIERS = frozenset({
    "gate", "bollard", "lift_gate", "swing_gate", "cycle_barrier",
})

BARRIER_QUALIFIER_TAGS = ("access", "motor_vehicle", "bicycle", "foot")

# Suffixes that imply higher functional class than highway=residential.
ARTERIAL_SUFFIX_RE = re.compile(
    r"\b(Boulevard|Parkway|Expressway|Pike|Highway|Crossing|Memorial)\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tags(el: dict) -> dict:
    """Return the element's tags dict, defaulting to empty."""
    t = el.get("tags") or {}
    return t if isinstance(t, dict) else {}


def _way_geom_pairs(way: dict) -> list[tuple[float, float]]:
    """Extract ``(lat, lon)`` pairs from a way record.

    Accepts both the Overpass raw shape (``geometry`` = list of
    ``{lat, lon}`` dicts) and the classify.py normalised shape
    (``geometry`` = list of ``[lat, lon]`` pairs).
    """
    geom = way.get("geometry") or []
    pairs: list[tuple[float, float]] = []
    for g in geom:
        if isinstance(g, dict):
            lat, lon = g.get("lat"), g.get("lon")
        elif isinstance(g, (list, tuple)) and len(g) >= 2:
            lat, lon = g[0], g[1]
        else:
            continue
        if lat is None or lon is None:
            continue
        if not valid_latlon(float(lat), float(lon)):
            continue
        pairs.append((float(lat), float(lon)))
    return pairs


def _name_for(el: dict) -> str | None:
    name = _tags(el).get("name")
    return name if isinstance(name, str) and name.strip() else None


# ---------------------------------------------------------------------------
# Detectors — ways
# ---------------------------------------------------------------------------

def detect_oneway_minus_one(ways: Iterable[dict]) -> list[dict]:
    """Flag ways with ``oneway=-1`` on Class-A-eligible highways.

    ``-1`` means the way is oneway against its drawn direction. It is a
    legitimate value but historically results from sloppy edits where a
    contributor reversed the geometry without updating the tag, producing a
    silently wrong directionality. These are mechanical-fix candidates but
    require human eyes — surfaced as findings, not auto-fixes.
    """
    out: list[dict] = []
    for w in ways:
        tags = _tags(w)
        if tags.get("highway") not in CLASS_A_HIGHWAYS:
            continue
        oneway = tags.get("oneway")
        if oneway is None:
            continue
        if str(oneway).strip() != "-1":
            continue
        out.append({
            "kind": "oneway_minus_one",
            "id": w.get("id"),
            "name": tags.get("name"),
            "severity": HIGH,
            "description": (
                f"oneway=-1 on highway={tags.get('highway')} "
                f"(name={tags.get('name') or 'unnamed'}); verify reversed-tag fix"
            ),
            "routing_impact": 4,
            "highway": tags.get("highway"),
            "geometry": _way_geom_pairs(w),
        })
    return out


def detect_oneway_conflicts(
    ways: Iterable[dict], threshold_m: float = 50.0,
) -> list[dict]:
    """Detect same-name parallel oneway segments that imply a routing defect.

    A LEGITIMATE divided carriageway has two ``oneway=yes`` ways with parallel
    geometry pointing in OPPOSITE directions — not a defect. The defect
    patterns we want to surface are:

    (a) two same-name ways, both ``oneway=yes``, geometries close, but their
        effective direction vectors point the SAME way — one of them has been
        digitised the wrong way round.
    (b) two same-name ways, one ``oneway=yes`` and one ``oneway=-1``, with
        geometries close and their *effective* direction vectors aligned the
        same way — direction was "fixed" by reversing the tag instead of the
        geometry.

    Implementation: pair candidates by lowercased name; require parallel-paired
    proximity (BOTH endpoints of one way must be within ``threshold_m`` of
    SOME vertex of the other, AND the closest-vertex-pair distance must be
    > 5 m so we don't trip on chained/sequentially-connected segments along
    the same physical street); then flag only when the dot product of the
    two effective along-vectors is positive (with a strict cushion so noisy
    near-perpendicular geometries don't squeak through). ``oneway=-1`` is
    folded into the effective direction by negating the geometric vector.
    """
    materialised: list[dict] = list(ways)

    # Group by lower-cased name.
    by_name: dict[str, list[dict]] = {}
    for w in materialised:
        tags = _tags(w)
        name = tags.get("name")
        if not name or not isinstance(name, str):
            continue
        if not is_oneway_truthy(tags.get("oneway")):
            continue
        key = name.strip().lower()
        if not key:
            continue
        by_name.setdefault(key, []).append(w)

    def _min_dist_to(
        pt: tuple[float, float],
        chain: list[tuple[float, float]],
    ) -> float:
        return min(haversine_m(pt[0], pt[1], q[0], q[1]) for q in chain)

    out: list[dict] = []
    for _key, group in by_name.items():
        if len(group) < 2:
            continue

        # Pre-compute geometry + normalised along-vectors per way.
        infos: list[
            tuple[dict, list[tuple[float, float]], tuple[float, float]]
        ] = []
        for w in group:
            pairs = _way_geom_pairs(w)
            if len(pairs) < 2:
                continue
            start = pairs[0]
            end = pairs[-1]
            dlat = end[0] - start[0]
            dlon = end[1] - start[1]
            mag = (dlat * dlat + dlon * dlon) ** 0.5
            if mag == 0:
                continue
            # oneway=-1 means the legal direction is end->start.
            if str(_tags(w).get("oneway")).strip() == "-1":
                dlat, dlon = -dlat, -dlon
            vec = (dlat / mag, dlon / mag)
            infos.append((w, pairs, vec))

        for i in range(len(infos)):
            wi, pi, vi = infos[i]
            for j in range(i + 1, len(infos)):
                wj, pj, vj = infos[j]

                # Distance from each endpoint of one way to closest vertex
                # on the other.
                d_start_i = _min_dist_to(pi[0], pj)
                d_end_i = _min_dist_to(pi[-1], pj)
                d_start_j = _min_dist_to(pj[0], pi)
                d_end_j = _min_dist_to(pj[-1], pi)

                # PARALLEL-PAIRED requirement: both endpoints of at least one
                # way must lie within threshold of the other's polyline. This
                # weeds out chained sequential segments along the same
                # physical street (where only the shared joining vertex is
                # close).
                pi_paired = (d_start_i <= threshold_m and d_end_i <= threshold_m)
                pj_paired = (d_start_j <= threshold_m and d_end_j <= threshold_m)
                if not (pi_paired or pj_paired):
                    continue

                # Reject sequentially-connected segments (sharing an endpoint
                # within ~5 m). A real parallel pair has both ways physically
                # offset along the perpendicular axis; chained segments on a
                # single oneway share a joining vertex.
                min_endpoint_sep = min(
                    d_start_i, d_end_i, d_start_j, d_end_j,
                )
                if min_endpoint_sep < 5.0:
                    continue

                # Same-direction = defect (one of them is mis-digitised or
                # mis-tagged). Anti-parallel = legitimate divided carriageway.
                # Strict cushion so noisy almost-perpendicular pairs are
                # ignored.
                dot = vi[0] * vj[0] + vi[1] * vj[1]
                if dot < 0.7:
                    continue

                # Reject pairs whose offset is LONGITUDINAL (aligned with the
                # way's own direction) rather than LATERAL (perpendicular to
                # it). On a long named arterial split into many oneway
                # segments, two segments on the same side of the carriageway
                # are chained-but-displaced — their start-to-start offset
                # points ALONG the road, not across it. A genuine same-side
                # defect pair has the offset pointing ACROSS the road.
                #
                # Project the midpoint-to-midpoint offset onto vi (the way's
                # unit along-vector). If the longitudinal component dominates
                # the lateral one, the offset is along-the-road — skip.
                # Use the geometric midpoint of each polyline (average of
                # endpoints) rather than the middle-vertex index, so two
                # ways spanning the same physical extent have aligned
                # midpoints regardless of which direction each was drawn.
                mid_i_pt = ((pi[0][0] + pi[-1][0]) / 2.0,
                            (pi[0][1] + pi[-1][1]) / 2.0)
                mid_j_pt = ((pj[0][0] + pj[-1][0]) / 2.0,
                            (pj[0][1] + pj[-1][1]) / 2.0)
                off_lat = mid_j_pt[0] - mid_i_pt[0]
                off_lon = mid_j_pt[1] - mid_i_pt[1]
                # Component of offset along vi (longitudinal) and the
                # orthogonal magnitude (lateral). Both in degrees; the ratio
                # is dimensionless.
                long_comp = off_lat * vi[0] + off_lon * vi[1]
                off_sq = off_lat * off_lat + off_lon * off_lon
                lat_sq = off_sq - long_comp * long_comp
                if lat_sq < 0:
                    lat_sq = 0.0
                if abs(long_comp) > (lat_sq ** 0.5) * 1.5:
                    continue

                tags_i = _tags(wi)
                mid_i = pi[len(pi) // 2]
                out.append({
                    "kind": "oneway_conflict",
                    "id": wi.get("id"),
                    "id_other": wj.get("id"),
                    "name": tags_i.get("name"),
                    "severity": CRITICAL,
                    "description": (
                        f"Same-name parallel oneway conflict: ways "
                        f"{wi.get('id')} and {wj.get('id')} "
                        f"(name={tags_i.get('name')}) point the same direction "
                        f"within {threshold_m:.0f} m — one is mis-digitised "
                        "or mis-tagged"
                    ),
                    "routing_impact": 5,
                    "lat": mid_i[0],
                    "lon": mid_i[1],
                })
    return out


def detect_access_blocked_residential(ways: Iterable[dict]) -> list[dict]:
    """Flag ``highway=residential`` ways tagged ``access=no``/``access=private``.

    Restricted to residential to avoid the dominant false-positive class:
    private driveways, parking aisles, and alleys tagged ``highway=service``.
    Those are legitimately access-restricted and not what a transit rider
    would expect to traverse. Skips ways that legitimately use
    ``motor_vehicle=destination`` (gated communities where driving is
    permitted for residents).
    """
    out: list[dict] = []
    for w in ways:
        tags = _tags(w)
        if tags.get("highway") != "residential":
            continue
        access = tags.get("access")
        if access not in ACCESS_BLOCKED_VALUES:
            continue
        if tags.get("motor_vehicle") == "destination":
            continue
        out.append({
            "kind": "access_blocked",
            "id": w.get("id"),
            "name": tags.get("name"),
            "severity": HIGH,
            "description": (
                f"access={access} on highway={tags.get('highway')} "
                f"({tags.get('name') or 'unnamed'}); routers will avoid this segment"
            ),
            "routing_impact": 4,
            "highway": tags.get("highway"),
            "access": access,
            "geometry": _way_geom_pairs(w),
        })
    return out


def detect_arterial_named_residential(ways: Iterable[dict]) -> list[dict]:
    """Flag ``highway=residential`` ways whose name ends in an arterial suffix.

    A road named "Reading Boulevard" or "Mason Pike" should usually be
    classified higher than residential. These cause routers to deprioritise
    legitimate arterials.
    """
    out: list[dict] = []
    for w in ways:
        tags = _tags(w)
        if tags.get("highway") != "residential":
            continue
        name = tags.get("name")
        if not name or not isinstance(name, str):
            continue
        if not ARTERIAL_SUFFIX_RE.search(name):
            continue
        out.append({
            "kind": "arterial_named_residential",
            "id": w.get("id"),
            "name": name,
            "severity": MEDIUM,
            "description": (
                f"highway=residential but name '{name}' ends in arterial suffix; "
                "verify functional class"
            ),
            "routing_impact": 3,
            "geometry": _way_geom_pairs(w),
        })
    return out


def detect_missing_maxspeed_arterial(ways: Iterable[dict]) -> list[dict]:
    """Flag tertiary/unclassified ways with no ``maxspeed`` tag.

    Restricted to ``tertiary`` and ``unclassified`` — the road tiers where
    routers most often pick the wrong class-default speed. Higher tiers
    (``secondary``/``primary``/``trunk``) overwhelmingly omit maxspeed
    legitimately and would dominate the finding list with non-actionable
    noise.
    """
    out: list[dict] = []
    for w in ways:
        tags = _tags(w)
        hwy = tags.get("highway")
        if hwy not in MISSING_MAXSPEED_HIGHWAYS:
            continue
        if tags.get("maxspeed"):
            continue
        out.append({
            "kind": "missing_maxspeed",
            "id": w.get("id"),
            "name": tags.get("name"),
            "severity": LOW,
            "description": (
                f"highway={hwy} has no maxspeed; routers fall back to defaults"
            ),
            "routing_impact": 2,
            "highway": hwy,
            "geometry": _way_geom_pairs(w),
        })
    return out


# ---------------------------------------------------------------------------
# Detectors — nodes
# ---------------------------------------------------------------------------

def detect_barriers_without_access(nodes: Iterable[dict]) -> list[dict]:
    """Flag traffic barriers (gate/bollard/...) with no access qualifier.

    Without a qualifier, OSM routers default to "barrier blocks all", which
    creates phantom routing dead-ends through residential streets.
    """
    out: list[dict] = []
    for n in nodes:
        tags = _tags(n)
        barrier = tags.get("barrier")
        if barrier not in QUALIFIED_BARRIERS:
            continue
        if any(tags.get(q) for q in BARRIER_QUALIFIER_TAGS):
            continue
        lat, lon = n.get("lat"), n.get("lon")
        out.append({
            "kind": "barrier_unqualified",
            "id": n.get("id"),
            "name": tags.get("name"),
            "severity": HIGH,
            "description": (
                f"barrier={barrier} with no access/motor_vehicle/bicycle/foot "
                "qualifier; routers will treat as fully blocked"
            ),
            "routing_impact": 4,
            "barrier": barrier,
            "lat": lat,
            "lon": lon,
        })
    return out


def detect_misplaced_bus_stops(
    bus_stops: Iterable[dict],
    ways: Iterable[dict],
    threshold_m: float = 20.0,
) -> list[dict]:
    """Flag bus stops further than ``threshold_m`` from any drivable-way vertex.

    "Drivable" excludes ``service=parking_aisle`` to avoid spuriously
    snapping a stop to a parking lot lane.
    """
    drivable_pts: list[tuple[float, float]] = []
    for w in ways:
        tags = _tags(w)
        if tags.get("highway") not in DRIVABLE_HIGHWAYS:
            continue
        if tags.get("highway") == "service" and tags.get("service") == "parking_aisle":
            continue
        drivable_pts.extend(_way_geom_pairs(w))

    out: list[dict] = []
    if not drivable_pts:
        return out

    for stop in bus_stops:
        lat = stop.get("lat")
        lon = stop.get("lon")
        if lat is None or lon is None:
            continue
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if not valid_latlon(lat_f, lon_f):
            continue
        # Coarse pre-filter: skip points more than ~0.005 deg (~500 m) from the
        # candidate's bbox. This is just to keep the inner haversine loop
        # cheap on large drivable-vertex sets — the precise check still uses
        # haversine.
        best = None
        for plat, plon in drivable_pts:
            if abs(plat - lat_f) > 0.01 and abs(plon - lon_f) > 0.01:
                continue
            d = haversine_m(lat_f, lon_f, plat, plon)
            if best is None or d < best:
                best = d
        if best is None:
            # Fall back to full scan if the pre-filter excluded everything.
            for plat, plon in drivable_pts:
                d = haversine_m(lat_f, lon_f, plat, plon)
                if best is None or d < best:
                    best = d
        if best is None or best <= threshold_m:
            continue
        tags = _tags(stop)
        out.append({
            "kind": "bus_stop_misplaced",
            "id": stop.get("id"),
            "name": tags.get("name"),
            "severity": MEDIUM,
            "description": (
                f"bus stop {stop.get('id')} is {best:.0f} m from nearest "
                f"drivable way (>{threshold_m:.0f} m threshold)"
            ),
            "routing_impact": 3,
            "lat": lat_f,
            "lon": lon_f,
            "distance_m": round(best, 1),
        })
    return out


# ---------------------------------------------------------------------------
# Detectors — relations
# ---------------------------------------------------------------------------

def detect_broken_turn_restrictions(relations: Iterable[dict]) -> list[dict]:
    """Flag malformed turn-restriction relations.

    A valid restriction must have at least one ``from``, one ``via``, and
    one ``to`` member, and a non-empty ``restriction`` tag.
    """
    out: list[dict] = []
    for r in relations:
        tags = _tags(r)
        if tags.get("type") != "restriction":
            continue
        members = r.get("members") or []
        if not isinstance(members, list):
            members = []

        roles: dict[str, list[Any]] = {}
        for m in members:
            if not isinstance(m, dict):
                continue
            role = m.get("role") or ""
            roles.setdefault(role, []).append(m)

        missing_roles = [
            role for role in ("from", "via", "to") if not roles.get(role)
        ]

        restriction_tag = tags.get("restriction") or tags.get("restriction:hgv")
        empty_restriction = not (restriction_tag and str(restriction_tag).strip())

        # Member-reference resolution: any member missing both ref and the
        # geom block that Overpass attaches when out geom is requested.
        unresolved = [
            m for m in members
            if isinstance(m, dict)
            and not m.get("ref")
            and not m.get("geometry")
            and not m.get("members")
        ]

        problems = []
        if missing_roles:
            problems.append("missing roles: " + ",".join(missing_roles))
        if empty_restriction:
            problems.append("no restriction tag")
        if unresolved:
            problems.append(f"{len(unresolved)} unresolved member(s)")

        if not problems:
            continue

        out.append({
            "kind": "broken_turn_restriction",
            "id": r.get("id"),
            "name": tags.get("name"),
            "severity": HIGH,
            "description": (
                f"Restriction relation {r.get('id')} is broken: "
                + "; ".join(problems)
            ),
            "routing_impact": 4,
            "problems": problems,
            "restriction": restriction_tag,
        })
    return out


__all__ = [
    "MEDIUM",
    "DRIVABLE_HIGHWAYS",
    "ARTERIAL_HIGHWAYS",
    "MISSING_MAXSPEED_HIGHWAYS",
    "ARTERIAL_SUFFIX_RE",
    "QUALIFIED_BARRIERS",
    "BARRIER_QUALIFIER_TAGS",
    "ACCESS_BLOCKED_VALUES",
    "ONEWAY_TRUTHY",
    "detect_oneway_minus_one",
    "detect_oneway_conflicts",
    "detect_access_blocked_residential",
    "detect_arterial_named_residential",
    "detect_missing_maxspeed_arterial",
    "detect_barriers_without_access",
    "detect_misplaced_bus_stops",
    "detect_broken_turn_restrictions",
]
