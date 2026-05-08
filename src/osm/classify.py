"""Defect classification: Class A (false oneway), B (multi-segment), AB (compound), C (residual)."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from .config import CLASS_A, CLASS_AB, CLASS_B, CLASS_C, CRITICAL, HIGH, LOW
from .gaps import detect_gaps
from .geo import norm_name, valid_latlon

log = logging.getLogger(__name__)

# Bug 3 / Bug 7: widen Class-A coverage beyond highway=residential, and accept
# all of OSM's truthy oneway encodings (yes, true, 1, -1).
CLASS_A_HIGHWAYS = frozenset({"residential", "unclassified", "tertiary", "service"})
ONEWAY_TRUTHY = frozenset({"yes", "true", "1", "-1"})


def is_oneway_truthy(value) -> bool:
    """Return True if an OSM ``oneway`` tag value is truthy.

    OSM treats ``yes``, ``true``, ``1``, and ``-1`` as oneway streets (``-1``
    means oneway in the reverse direction). Bare exact-string ``"yes"`` checks
    miss the alternate forms, especially ``-1`` on TIGER residuals.
    """
    if value is None:
        return False
    return str(value).strip().lower() in ONEWAY_TRUTHY


def _split_elements(raw: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Partition Overpass elements into (ways, nodes, relations).

    Tolerant of unknown element types (returned as ``None`` ``type``, future
    Overpass additions, etc.) — they're just skipped.
    """
    ways: list[dict] = []
    nodes: list[dict] = []
    relations: list[dict] = []
    for el in raw.get("elements", []) or []:
        et = el.get("type")
        if et == "way":
            ways.append(el)
        elif et == "node":
            nodes.append(el)
        elif et == "relation":
            relations.append(el)
        # else: silently ignore — unknown future types shouldn't crash.
    return ways, nodes, relations


def _safe_run(name: str, fn: Callable[..., list[dict]], *args, **kwargs) -> list[dict]:
    """Call a detector; log + return [] on any error so one bad detector
    doesn't kill the classify run."""
    try:
        result = fn(*args, **kwargs)
        return result if isinstance(result, list) else []
    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        log.warning("Detector %s failed: %s", name, exc)
        return []


def classify(raw: dict) -> dict:
    """Classify all way elements from an Overpass response into defect classes.

    Returns a dict with all_ways, class_a, class_a_only, class_ab,
    class_b_streets, gaps, summary_stats, and extra_findings.
    """
    elements_ways, elements_nodes, elements_relations = _split_elements(raw)
    elements = elements_ways
    by_norm: dict[str, list[dict]] = defaultdict(list)

    all_ways: list[dict] = []
    skipped_geom = 0
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        norm = norm_name(name)
        geom = el.get("geometry") or []
        geom_pairs = [
            [g["lat"], g["lon"]]
            for g in geom
            if "lat" in g and "lon" in g and valid_latlon(g["lat"], g["lon"])
        ]
        if not geom_pairs:
            skipped_geom += 1

        record = {
            "id": el.get("id"),
            "name": name,
            "name_display": name if name else "[Unnamed]",
            "name_key": norm,
            "highway": tags.get("highway"),
            "oneway": tags.get("oneway"),
            "tiger_reviewed": tags.get("tiger:reviewed"),
            "tiger_name_base": tags.get("tiger:name_base"),
            "tiger_cfcc": tags.get("tiger:cfcc"),
            "surface": tags.get("surface"),
            "lanes": tags.get("lanes"),
            "maxspeed": tags.get("maxspeed"),
            "geometry": geom_pairs,
            # Metadata fields from `out meta`
            "version": el.get("version"),
            "timestamp": el.get("timestamp"),
            "changeset": el.get("changeset"),
            "user": el.get("user"),
            "uid": el.get("uid"),
        }
        all_ways.append(record)
        if norm is not None:
            by_norm[norm].append(record)

    class_b_norm_keys = {k for k, ways in by_norm.items() if len(ways) >= 2}

    for w in all_ways:
        is_a = w["highway"] in CLASS_A_HIGHWAYS and is_oneway_truthy(w["oneway"])
        is_b = w["name_key"] is not None and w["name_key"] in class_b_norm_keys
        if is_a and is_b:
            w["defect_class"] = CLASS_AB
            w["severity"] = CRITICAL
        elif is_a:
            w["defect_class"] = CLASS_A
            w["severity"] = CRITICAL
        elif is_b:
            w["defect_class"] = CLASS_B
            w["severity"] = HIGH
        else:
            w["defect_class"] = CLASS_C
            w["severity"] = LOW

    class_a = [w for w in all_ways if w["defect_class"] in (CLASS_A, CLASS_AB)]
    class_ab = [w for w in all_ways if w["defect_class"] == CLASS_AB]
    class_a_only = [w for w in all_ways if w["defect_class"] == CLASS_A]

    class_b_streets: dict[str, list[dict]] = {}
    for norm_key in class_b_norm_keys:
        ways = by_norm[norm_key]
        display = ways[0]["name"]
        class_b_streets[display] = ways

    by_highway: dict[str, int] = defaultdict(int)
    for w in all_ways:
        by_highway[w["highway"] or "(unset)"] += 1
    by_class: dict[str, int] = defaultdict(int)
    for w in all_ways:
        by_class[w["defect_class"]] += 1

    residential_count = sum(1 for w in all_ways if w["highway"] == "residential")
    oneway_yes_total = sum(1 for w in all_ways if is_oneway_truthy(w["oneway"]))

    gaps = detect_gaps(class_b_streets)

    if skipped_geom:
        log.warning(
            "%d ways had missing or invalid geometry (rendered without polylines).",
            skipped_geom,
        )

    # Rider-impact detectors. These run on the raw harvested elements
    # (ways still carry their dict-shape Overpass geometry) so detectors that
    # need original tags work without re-deriving them. Each is wrapped in
    # _safe_run so a single broken detector cannot kill the audit.
    from . import detectors as _det  # local import to avoid cycle at import time

    bus_stops = [
        n for n in elements_nodes
        if (n.get("tags") or {}).get("highway") == "bus_stop"
    ]
    barrier_nodes = [
        n for n in elements_nodes
        if (n.get("tags") or {}).get("barrier")
    ]

    extra_findings: list[dict] = []
    extra_findings.extend(
        _safe_run("oneway_minus_one", _det.detect_oneway_minus_one, elements_ways)
    )
    extra_findings.extend(
        _safe_run("oneway_conflicts", _det.detect_oneway_conflicts, elements_ways)
    )
    extra_findings.extend(
        _safe_run(
            "access_blocked_residential",
            _det.detect_access_blocked_residential,
            elements_ways,
        )
    )
    extra_findings.extend(
        _safe_run(
            "barriers_without_access",
            _det.detect_barriers_without_access,
            barrier_nodes,
        )
    )
    extra_findings.extend(
        _safe_run(
            "broken_turn_restrictions",
            _det.detect_broken_turn_restrictions,
            elements_relations,
        )
    )
    extra_findings.extend(
        _safe_run(
            "arterial_named_residential",
            _det.detect_arterial_named_residential,
            elements_ways,
        )
    )
    extra_findings.extend(
        _safe_run(
            "missing_maxspeed_arterial",
            _det.detect_missing_maxspeed_arterial,
            elements_ways,
        )
    )
    extra_findings.extend(
        _safe_run(
            "misplaced_bus_stops",
            _det.detect_misplaced_bus_stops,
            bus_stops,
            elements_ways,
        )
    )

    findings_by_kind: dict[str, int] = defaultdict(int)
    for f in extra_findings:
        findings_by_kind[f.get("kind") or ""] += 1

    summary_stats = {
        "total": len(all_ways),
        "residential": residential_count,
        "oneway_yes_total": oneway_yes_total,
        "class_a_count": len(class_a),
        "class_a_only_count": len(class_a_only),
        "class_ab_count": len(class_ab),
        "class_b_street_count": len(class_b_streets),
        "class_b_way_count": sum(
            1 for w in all_ways if w["defect_class"] in (CLASS_B, CLASS_AB)
        ),
        "gaps_found": len(gaps),
        "ways_missing_geom": skipped_geom,
        "under_sanity_threshold": bool(raw.get("_under_threshold", False)),
        "cache_used": bool(raw.get("_cache_used", False)),
        "cache_age_seconds": raw.get("_cache_age_seconds"),
        "by_highway": dict(by_highway),
        "by_class": dict(by_class),
        # Rider-impact findings counts (extend the inventory beyond TIGER ways).
        "findings_oneway_minus_one": findings_by_kind.get("oneway_minus_one", 0),
        "findings_oneway_conflicts": findings_by_kind.get("oneway_conflict", 0),
        "findings_access_blocked": findings_by_kind.get("access_blocked", 0),
        "findings_barriers_unqualified": findings_by_kind.get("barrier_unqualified", 0),
        "findings_broken_turn_restrictions":
            findings_by_kind.get("broken_turn_restriction", 0),
        "findings_arterial_named_residential":
            findings_by_kind.get("arterial_named_residential", 0),
        "findings_missing_maxspeed": findings_by_kind.get("missing_maxspeed", 0),
        "findings_bus_stops_misplaced": findings_by_kind.get("bus_stop_misplaced", 0),
        "findings_total": len(extra_findings),
    }

    return {
        "all_ways": all_ways,
        "class_a": class_a,
        "class_a_only": class_a_only,
        "class_ab": class_ab,
        "class_b_streets": class_b_streets,
        "gaps": gaps,
        "summary_stats": summary_stats,
        "extra_findings": extra_findings,
    }
