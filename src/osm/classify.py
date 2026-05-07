"""Defect classification: Class A (false oneway), B (multi-segment), AB (compound), C (residual)."""

from __future__ import annotations

import logging
from collections import defaultdict

from .config import CLASS_A, CLASS_AB, CLASS_B, CLASS_C, CRITICAL, HIGH, LOW
from .gaps import detect_gaps
from .geo import norm_name, valid_latlon

log = logging.getLogger(__name__)


def classify(raw: dict) -> dict:
    """Classify all way elements from an Overpass response into defect classes.

    Returns a dict with all_ways, class_a, class_a_only, class_ab,
    class_b_streets, gaps, and summary_stats.
    """
    elements = [e for e in raw.get("elements", []) if e.get("type") == "way"]
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
        is_a = w["highway"] == "residential" and w["oneway"] == "yes"
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
    oneway_yes_total = sum(1 for w in all_ways if w["oneway"] == "yes")

    gaps = detect_gaps(class_b_streets)

    if skipped_geom:
        log.warning(
            "%d ways had missing or invalid geometry (rendered without polylines).",
            skipped_geom,
        )

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
        "by_highway": dict(by_highway),
        "by_class": dict(by_class),
    }

    return {
        "all_ways": all_ways,
        "class_a": class_a,
        "class_a_only": class_a_only,
        "class_ab": class_ab,
        "class_b_streets": class_b_streets,
        "gaps": gaps,
        "summary_stats": summary_stats,
    }
