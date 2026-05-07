"""CSV export — 4 sorted slices (ported from Tiger)."""

from __future__ import annotations

import csv
from pathlib import Path

from .config import CLASS_ORDER


def _csv_row(w: dict) -> dict:
    return {
        "way_id": w["id"],
        "name": w["name_display"],
        "highway": w["highway"] or "",
        "oneway": w["oneway"] or "",
        "defect_class": w["defect_class"],
        "severity": w["severity"],
        "tiger_cfcc": w.get("tiger_cfcc") or "",
        "tiger_name_base": w.get("tiger_name_base") or "",
        "review_status": w.get("review_status", ""),
        "last_editor": w.get("user", ""),
        "last_edit": w.get("timestamp", ""),
    }


ALL_FIELDS = [
    "way_id", "name", "highway", "oneway", "defect_class", "severity",
    "tiger_cfcc", "tiger_name_base", "review_status", "last_editor", "last_edit",
]

MULTI_SEG_FIELDS = ALL_FIELDS + ["_street_gap_count"]


def write_csvs(classified: dict, csv_dir: Path) -> None:
    """Write the 4 CSV slices to csv_dir."""
    csv_dir.mkdir(parents=True, exist_ok=True)
    class_rank = {c: i for i, c in enumerate(CLASS_ORDER)}

    # all_ways.csv
    sorted_ways = sorted(
        classified["all_ways"],
        key=lambda w: (class_rank[w["defect_class"]], w.get("name_display", "").lower(), w["id"] or 0),
    )
    _write_csv(csv_dir / "all_ways.csv", ALL_FIELDS, [_csv_row(w) for w in sorted_ways])

    # class_a_false_oneway.csv
    class_a = [w for w in classified["all_ways"] if w["defect_class"] in ("A", "AB")]
    class_a.sort(key=lambda w: (w.get("name_display", "").lower(), w["id"] or 0))
    _write_csv(csv_dir / "class_a_false_oneway.csv", ALL_FIELDS, [_csv_row(w) for w in class_a])

    # class_ab_compound.csv
    class_ab = [w for w in classified["all_ways"] if w["defect_class"] == "AB"]
    class_ab.sort(key=lambda w: (w.get("name_display", "").lower(), w["id"] or 0))
    _write_csv(csv_dir / "class_ab_compound.csv", ALL_FIELDS, [_csv_row(w) for w in class_ab])

    # class_b_multi_segment.csv — sorted by gap count then segment count
    gap_count_by_street: dict[str, int] = {}
    for g in classified.get("gaps", []):
        street = g.get("street", "")
        gap_count_by_street[street] = gap_count_by_street.get(street, 0) + 1

    multi_seg_rows: list[dict] = []
    for street, ways in classified["class_b_streets"].items():
        for w in ways:
            row = _csv_row(w)
            row["_street_gap_count"] = gap_count_by_street.get(street, 0)
            multi_seg_rows.append(row)
    multi_seg_rows.sort(key=lambda r: (-r["_street_gap_count"], r["name"].lower(), r["way_id"] or 0))
    _write_csv(csv_dir / "class_b_multi_segment.csv", MULTI_SEG_FIELDS, multi_seg_rows)

    print(f"  CSVs saved: {csv_dir}")


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
