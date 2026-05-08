"""MapRoulette challenge generator for unverified Class-A defects.

Phase 3 of the remediation plan: convert the Class-A and Class-AB
candidates that lack high-confidence CAGIS verification from a
do-not-submit liability into a community-reviewed contribution.

These are ways the classifier flagged as having a probable false
``oneway=yes``/`-1` tag (TIGER-fixup heuristic) but for which the
CAGIS conflation either could not match (no centerline within
``FALLBACK_BUFFER_M``) or matched only at REVIEW confidence
(0.6 ≤ confidence < 0.85). The mechanical-fix pipeline correctly
refuses to auto-submit them; MapRoulette is the right escalation
path for "human eyes here, please."

Output format
-------------
MapRoulette ingests "GeoJSON Lines" (newline-delimited GeoJSON
features), one feature per task. Each feature carries:

* ``geometry`` — the OSM way's polyline (LineString)
* ``properties.task_name`` — short human-readable identifier
* ``properties.task_instruction`` — Markdown shown to mappers
* ``properties.osm_link`` — direct link to the way on osm.org
* ``properties.cagis_match`` — when present, the candidate CAGIS
  centerline so the mapper can compare directly

A challenge is the union of all task features for a zone. The plan
calls for one challenge per zone; this module emits one .geojson
file per zone, ready for upload via the MapRoulette web UI or
the ``mr-cli`` cooperative-challenge flow.

Etiquette
---------
* Only includes ways inside the zone polygon (already enforced by
  the polygon clip in :mod:`osm.fetch`).
* Skips any way whose CAGIS confidence ≥ ``HIGH_CONFIDENCE`` — those
  go through the auto-submit path instead of MapRoulette.
* Marks each task with ``priority`` based on defect class so AB
  candidates surface above plain A.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CLASS_A, CLASS_AB
from .conflate import HIGH_CONFIDENCE, REVIEW_CONFIDENCE

log = logging.getLogger(__name__)

# Task priority numerals follow the MapRoulette convention:
# 0 = HIGH (surface first), 1 = MEDIUM, 2 = LOW.
PRIORITY_HIGH = 0
PRIORITY_MEDIUM = 1
PRIORITY_LOW = 2

# Lifted from review.py's FIX_REVIEW_BAND for symmetry: any way with a
# CAGIS confidence at or above HIGH_CONFIDENCE goes through the auto-submit
# path; below REVIEW_CONFIDENCE the CAGIS match is too weak to even cite
# as a hint. The MapRoulette challenge surfaces ways in [0.0, HIGH).
MR_INCLUDE_KINDS: frozenset[str] = frozenset({CLASS_A, CLASS_AB})


@dataclass
class MapRouletteTask:
    """One feature in the MapRoulette GeoJSON output."""

    way_id: int
    name: str | None
    defect_class: str
    geometry_latlon: list[list[float]]
    cagis_match: dict | None
    instruction: str
    priority: int


def _osm_way_url(way_id: object) -> str:
    return f"https://www.openstreetmap.org/way/{way_id}"


def _instruction_for(way: dict) -> str:
    """Markdown shown to MapRoulette mappers for a single task."""
    name = way.get("name_display") or way.get("name") or "(unnamed)"
    cls = (way.get("defect_class") or "").upper()
    osm_oneway = (way.get("oneway") or "").strip()
    cm = way.get("cagis_match") or {}
    confidence = cm.get("confidence")

    lines: list[str] = []
    lines.append(
        f"OSM way **{way.get('id')}** ({name}) is tagged "
        f"`oneway={osm_oneway}` but the MetroNow audit pipeline "
        f"(Class {cls}) suspects this is a TIGER-import artefact "
        f"that should be removed."
    )
    if cm and confidence is not None:
        if confidence >= REVIEW_CONFIDENCE:
            lines.append("")
            lines.append(
                f"CAGIS confidence: **{confidence:.2f}** "
                f"(REVIEW band — strong signal but below the auto-submit "
                f"threshold of {HIGH_CONFIDENCE:.2f})."
            )
            cagis_id = cm.get("cagis_id")
            cagis_oneway = cm.get("cagis_oneway", "no")
            if cagis_id is not None:
                lines.append(
                    f"CAGIS centerline `{cagis_id}` says oneway = "
                    f"**{cagis_oneway}**. If you confirm the OSM way is "
                    "in fact bidirectional, please remove the "
                    "`oneway=yes` tag."
                )
        else:
            lines.append("")
            lines.append(
                f"CAGIS confidence: **{confidence:.2f}** (below review "
                "threshold; treat as a weak signal). Use OSM editor "
                "imagery and your local knowledge to decide."
            )
    else:
        lines.append("")
        lines.append(
            "No CAGIS centerline matched within "
            "100 m of this way — this challenge is based purely on the "
            "TIGER-fixup heuristic. Use editor imagery and local "
            "knowledge to decide."
        )

    lines.append("")
    lines.append(f"[View on OSM]({_osm_way_url(way.get('id'))})")
    lines.append("")
    lines.append(
        "_Sourced by the MetroNow audit pipeline_ — see "
        "https://wiki.openstreetmap.org/wiki/Hamilton_County_TIGER_Audit."
    )
    return "\n".join(lines)


def _priority_for(way: dict) -> int:
    """AB defects surface above plain A (compound defects are higher signal)."""
    cls = (way.get("defect_class") or "").upper()
    if cls == CLASS_AB:
        return PRIORITY_HIGH
    if cls == CLASS_A:
        return PRIORITY_MEDIUM
    return PRIORITY_LOW


def unverified_class_a_ways(classified: dict) -> list[dict]:
    """Return Class A / AB ways that did NOT make the auto-submit pool.

    A way qualifies when:

    * ``defect_class`` is ``A`` or ``AB``; AND
    * either no ``cagis_match`` OR ``cagis_match.confidence`` < HIGH_CONFIDENCE.

    Confidence above HIGH already goes through the mechanical-fix
    pipeline, so MapRoulette would duplicate work.
    """
    out: list[dict] = []
    for w in classified.get("all_ways", []):
        cls = (w.get("defect_class") or "").upper()
        if cls not in MR_INCLUDE_KINDS:
            continue
        cm = w.get("cagis_match") or {}
        confidence = cm.get("confidence")
        if isinstance(confidence, (int, float)) and confidence >= HIGH_CONFIDENCE:
            continue
        if not w.get("geometry"):
            continue
        out.append(w)
    return out


def build_tasks(ways: list[dict]) -> list[MapRouletteTask]:
    """Project Class-A/AB way dicts into :class:`MapRouletteTask` rows."""
    tasks: list[MapRouletteTask] = []
    for w in ways:
        way_id = w.get("id")
        if way_id is None:
            continue
        tasks.append(MapRouletteTask(
            way_id=int(way_id),
            name=w.get("name_display") or w.get("name"),
            defect_class=(w.get("defect_class") or "").upper(),
            geometry_latlon=list(w["geometry"]),
            cagis_match=w.get("cagis_match"),
            instruction=_instruction_for(w),
            priority=_priority_for(w),
        ))
    return tasks


def task_to_feature(task: MapRouletteTask) -> dict:
    """Serialise one task as a GeoJSON Feature.

    Geometry is a LineString with ``[lon, lat]`` pairs (GeoJSON order),
    converted from the in-pipeline ``[lat, lon]`` format.
    """
    coords = [[p[1], p[0]] for p in task.geometry_latlon if len(p) >= 2]
    properties: dict[str, Any] = {
        "task_name": (
            f"Way {task.way_id}: {task.name or '(unnamed)'} "
            f"(Class {task.defect_class})"
        ),
        "task_instruction": task.instruction,
        "osm_link": _osm_way_url(task.way_id),
        "way_id": task.way_id,
        "defect_class": task.defect_class,
        "priority": task.priority,
    }
    if task.cagis_match:
        properties["cagis_match"] = task.cagis_match
    if task.name:
        properties["name"] = task.name
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": properties,
    }


def write_geojsonl(tasks: list[MapRouletteTask], out_path: Path) -> int:
    """Write tasks as line-delimited GeoJSON (the MapRoulette ingest format).

    One feature per line, no enclosing FeatureCollection wrapper. Returns
    the number of tasks written.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for task in tasks:
            fh.write(json.dumps(task_to_feature(task), ensure_ascii=False))
            fh.write("\n")
            n += 1
    log.info("MapRoulette: wrote %d task(s) to %s", n, out_path)
    return n


def challenge_metadata(zone_name: str, zone_key: str, n_tasks: int) -> dict:
    """Suggested challenge-level metadata (description, instruction, tags).

    MapRoulette's challenge object is created via the web UI or
    ``mr-cli``; this dict is a recommended payload for the form. The
    instruction here is the *challenge* instruction (shown alongside
    the AOI map); per-task instructions live in each feature's
    ``task_instruction`` property.
    """
    return {
        "name": f"MetroNow TIGER Audit — {zone_name}",
        "description": (
            f"Class A / AB candidates from the MetroNow OSM TIGER audit "
            f"for the {zone_name} on-demand microtransit zone. "
            f"{n_tasks} ways flagged as having a probable false "
            f"`oneway=yes` tag inherited from the 2007–2008 TIGER import. "
            f"CAGIS confidence is below the auto-submit threshold of "
            f"{HIGH_CONFIDENCE:.2f}, so each task needs human verification "
            "before any tag change is made."
        ),
        "instruction": (
            "Open the way in your preferred editor (JOSM, iD). "
            "Look at the imagery and confirm whether the street is "
            "actually one-way. If it is bidirectional, remove the "
            "`oneway=yes` tag. If it is genuinely one-way, mark the "
            "task as `Already Fixed` so the audit doesn't re-flag it.\n\n"
            "**Source:** MetroNow audit pipeline — "
            "https://wiki.openstreetmap.org/wiki/Hamilton_County_TIGER_Audit"
        ),
        "checkin_comment": (
            "MetroNow TIGER audit (manual review via MapRoulette challenge "
            f"for {zone_key})"
        ),
        "checkin_source": "MetroNow TIGER Audit / MapRoulette",
        "tags": "tiger;tiger_audit;oneway;cincinnati;sorta;metronow",
    }


# ---------------------------------------------------------------------------
# Phase 3 follow-up: node-disconnect gap challenges
#
# Class B/AB ways that share a normalized name and have endpoints within
# the gap detector's threshold are surfaced as candidate node disconnects
# (gaps.py). These can't go through CAGIS auto-submission — joining two
# ways at a node is a topological edit, not a tag change — so they're
# the natural MapRoulette population. One task per candidate disconnect.
# ---------------------------------------------------------------------------

@dataclass
class GapTask:
    """One gap candidate projected to a MapRoulette task."""

    way1_id: int
    way2_id: int
    street: str | None
    distance_m: float
    lat: float
    lon: float
    instruction: str


def _gap_instruction(gap: dict) -> str:
    """Markdown shown to mappers for a single gap candidate."""
    name = gap.get("street") or "(unnamed)"
    d = gap.get("distance_m")
    d_str = f"{d:.1f} m" if isinstance(d, (int, float)) else "unknown"
    way1, way2 = gap.get("way1_id"), gap.get("way2_id")
    lines = [
        f"Two same-named segments of **{name}** sit {d_str} apart but "
        "are not joined at a shared node. The MetroNow audit pipeline "
        "(Class B node-disconnect heuristic) suspects they should be "
        "connected — a routing engine reading the OSM data would refuse "
        "to traverse the gap.",
        "",
        f"* Way A: {_osm_way_url(way1)}" if way1 is not None else "",
        f"* Way B: {_osm_way_url(way2)}" if way2 is not None else "",
        "",
        "**Action:** in your preferred editor (JOSM, iD), confirm "
        "whether the two ways should share a node at this point. If "
        "they should, join them. If the gap is intentional (a closed "
        "alley, a missing private driveway, two streets that genuinely "
        "share a name without connecting), mark the task as "
        "`Already Fixed` so the audit doesn't re-flag it.",
        "",
        "_Sourced by the MetroNow audit pipeline_ — see "
        "https://wiki.openstreetmap.org/wiki/Hamilton_County_TIGER_Audit.",
    ]
    return "\n".join(filter(None, lines))


def unverified_gaps(classified: dict) -> list[dict]:
    """Return gap candidates with usable lat/lon coords."""
    out: list[dict] = []
    for g in classified.get("gaps", []):
        lat = g.get("lat")
        lon = g.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        out.append(g)
    return out


def build_gap_tasks(gaps: list[dict]) -> list[GapTask]:
    """Project gap dicts into :class:`GapTask` rows."""
    tasks: list[GapTask] = []
    for g in gaps:
        raw1 = g.get("way1_id")
        raw2 = g.get("way2_id")
        try:
            way1 = int(raw1) if raw1 is not None else 0
            way2 = int(raw2) if raw2 is not None else 0
        except (TypeError, ValueError):
            continue
        try:
            lat = float(g["lat"])
            lon = float(g["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        d_raw = g.get("distance_m")
        try:
            distance = float(d_raw) if d_raw is not None else 0.0
        except (TypeError, ValueError):
            distance = 0.0
        tasks.append(GapTask(
            way1_id=way1,
            way2_id=way2,
            street=g.get("street"),
            distance_m=distance,
            lat=lat,
            lon=lon,
            instruction=_gap_instruction(g),
        ))
    return tasks


def gap_task_to_feature(task: GapTask) -> dict:
    """GeoJSON Point Feature for a single gap task."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [task.lon, task.lat],
        },
        "properties": {
            "task_name": (
                f"Node-disconnect: {task.street or '(unnamed)'} "
                f"({task.distance_m:.1f} m gap)"
            ),
            "task_instruction": task.instruction,
            "way1_id": task.way1_id,
            "way2_id": task.way2_id,
            "street": task.street,
            "distance_m": task.distance_m,
            "priority": PRIORITY_MEDIUM,
        },
    }


def write_gap_geojsonl(tasks: list[GapTask], out_path: Path) -> int:
    """Write gap tasks as line-delimited GeoJSON. Same shape as
    :func:`write_geojsonl` but for Point features instead of LineStrings."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for task in tasks:
            fh.write(json.dumps(gap_task_to_feature(task), ensure_ascii=False))
            fh.write("\n")
            n += 1
    log.info("MapRoulette: wrote %d gap task(s) to %s", n, out_path)
    return n


def gap_challenge_metadata(zone_name: str, zone_key: str, n_tasks: int) -> dict:
    """Suggested challenge-level metadata for the gaps challenge."""
    return {
        "name": f"MetroNow TIGER Audit — {zone_name} (node disconnects)",
        "description": (
            f"Candidate node disconnects from the MetroNow OSM TIGER audit "
            f"for the {zone_name} on-demand microtransit zone. "
            f"{n_tasks} pairs of same-named OSM ways have endpoints within "
            "30 m of each other but no shared node — likely a routing "
            "graph break. Each task asks a mapper to confirm whether the "
            "two ways should be joined."
        ),
        "instruction": (
            "Open the location in your preferred editor (JOSM, iD). "
            "Look at the two same-named ways and decide if they should "
            "share a node. If they should, join them at the gap. If the "
            "gap is intentional, mark the task as `Already Fixed`.\n\n"
            "**Source:** MetroNow audit pipeline — "
            "https://wiki.openstreetmap.org/wiki/Hamilton_County_TIGER_Audit"
        ),
        "checkin_comment": (
            "MetroNow TIGER audit (node-disconnect review via MapRoulette "
            f"challenge for {zone_key})"
        ),
        "checkin_source": "MetroNow TIGER Audit / MapRoulette",
        "tags": "tiger;tiger_audit;node_disconnect;cincinnati;sorta;metronow",
    }
