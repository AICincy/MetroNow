"""Leaflet HTML dashboard generation.

Produces a self-contained HTML file with embedded data, Leaflet map,
sidebar with KPI cards, layer toggles, search, dark mode, keyboard
shortcuts, and JOSM integration.  Ported from Tiger's DASHBOARD_TEMPLATE.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import CLASS_C

log = logging.getLogger(__name__)
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"


def _compact_ways(all_ways: list[dict]) -> list[dict]:
    """Compact way records for embedding in the dashboard."""
    return [
        {
            "id": w["id"],
            "h": w["highway"] or "",
            "n": w["name_display"],
            "o": w["oneway"] or "",
            "c": w["defect_class"],
            "s": w["severity"],
            "g": w["geometry"],
            "rs": w.get("review_status", ""),
        }
        for w in all_ways
        if w["geometry"]
    ]


def _compact_gaps(gaps: list[dict]) -> list[dict]:
    return [
        {
            "lat": g["lat"],
            "lon": g["lon"],
            "street": g["street"],
            "way1_id": g["way1_id"],
            "way2_id": g["way2_id"],
            "distance_m": g["distance_m"],
        }
        for g in gaps
    ]


def write_dashboard(
    classified: dict,
    zone_key: str,
    zone_name: str,
    out_path: Path,
    audit_ts: str,
) -> None:
    """Generate the interactive Leaflet dashboard HTML."""
    stats = classified["summary_stats"]
    ways_json = json.dumps(_compact_ways(classified["all_ways"]), separators=(",", ":"))
    gaps_json = json.dumps(_compact_gaps(classified.get("gaps", [])), separators=(",", ":"))
    stats_json = json.dumps({
        "total": stats["total"],
        "residential": stats["residential"],
        "oneway": stats["oneway_yes_total"],
        "class_a": stats["class_a_count"],
        "class_b": stats["class_b_way_count"],
        "class_ab": stats["class_ab_count"],
        "class_c": stats.get("by_class", {}).get(CLASS_C, 0),
        "multi_seg_streets": stats["class_b_street_count"],
        "gaps_found": stats["gaps_found"],
    }, separators=(",", ":"))

    import html as html_mod
    safe_zone_name = html_mod.escape(zone_name)
    safe_zone_key = html_mod.escape(zone_key)
    safe_audit_ts = html_mod.escape(audit_ts)
    safe_ways = ways_json.replace("</", "<\\/")
    safe_gaps = gaps_json.replace("</", "<\\/")
    safe_stats = stats_json.replace("</", "<\\/")

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    out_html = template.replace("{{ZONE_NAME}}", safe_zone_name)
    out_html = out_html.replace("{{ZONE_KEY}}", safe_zone_key)
    out_html = out_html.replace("{{AUDIT_TS}}", safe_audit_ts)
    out_html = out_html.replace("{{WAYS_DATA}}", safe_ways)
    out_html = out_html.replace("{{GAPS_DATA}}", safe_gaps)
    out_html = out_html.replace("{{STATS_DATA}}", safe_stats)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(out_html)
    log.info("Dashboard saved: %s", out_path)

