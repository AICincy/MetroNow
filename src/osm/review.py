"""Terminal-based review UI for proposed corrections.

Three layers of fix proposals:

1. **Heuristic** — :func:`proposed_fix` (kept for backwards compatibility)
   detects Class A/AB ways with truthy ``oneway`` tags and proposes
   removing the tag. No external evidence; flagged for human review.

2. **CAGIS-verified** — :func:`proposed_fixes_for_way` produces one or more
   fixes per way using the way's ``cagis_match`` (set by
   :mod:`osm.conflate`). Fixes carry ``source_evidence`` linking back to
   the CAGIS feature and are auto-submittable when confidence ≥ 0.85.

   Source: CAGIS Open Data Hub, Hamilton County, Ohio.

3. **TIGER-verified (fallback)** — when no high-confidence CAGIS match
   exists for a way, :func:`proposed_fixes_for_way` also consults
   ``tiger_match`` (set by :mod:`osm.tiger2024`) and emits ``set_name_tiger``
   / ``reclass_highway_tiger`` fixes. TIGER fixes are always
   ``requires_human_review=True`` because TIGER is a less-current,
   coarser-class baseline than CAGIS.

   Source: U.S. Census Bureau, TIGER/Line 2024 (public domain).
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from osm.classify import is_oneway_truthy
from osm.config import CLASS_ORDER
from osm.geo import norm_name

console = Console()

# Confidence thresholds (mirrored in osm.conflate; duplicated here so review
# logic doesn't need to import the heavyweight conflate module just for two
# floats).
HIGH_CONFIDENCE = 0.85
REVIEW_CONFIDENCE = 0.6

# Values of CAGIS ``oneway`` (decoded by osm.conflate._decode_oneway) that
# mean "not a oneway" in OSM terms.
_NOT_ONEWAY = frozenset({"no", "", None})  # type: ignore[arg-type]


def display_issue(way: dict, index: int, total: int) -> None:
    """Display a single defect for review."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Way ID", str(way.get("id", "?")))
    table.add_row("Street", way.get("name_display", "[Unnamed]"))
    table.add_row("Highway", way.get("highway", "?"))
    table.add_row("Oneway", way.get("oneway", "(not set)"))
    table.add_row("Defect Class", way.get("defect_class", "?"))
    table.add_row("Severity", way.get("severity", "?"))
    table.add_row("Review Status", way.get("review_status", "?"))
    table.add_row("Review Reason", way.get("review_reason", "?"))

    fix = proposed_fix(way)
    if fix:
        table.add_row("Proposed Fix", fix["description"])

    cagis = way.get("cagis_match")
    if cagis:
        table.add_row(
            "CAGIS Match",
            f"{cagis.get('cagis_name')} (id {cagis.get('cagis_id')}, "
            f"conf {cagis.get('confidence', 0):.2f})",
        )

    console.print(Panel(
        table,
        title=f"[bold]Issue {index}/{total}[/bold]",
        border_style="yellow" if way.get("severity") == "CRITICAL" else "blue",
    ))


def proposed_fix(way: dict) -> dict | None:
    """Generate a single proposed fix for a classified defect (legacy entry).

    Preserves the original behaviour: only emits the Class A/AB oneway-removal
    fix. CAGIS evidence, when present, is attached as ``source_evidence`` so
    downstream submission can include it in changeset metadata. New code
    should call :func:`proposed_fixes_for_way` to get the full list of
    CAGIS-verified fixes (oneway + name + maxspeed).
    """
    fixes = proposed_fixes_for_way(way)
    if not fixes:
        return None
    # Preserve the legacy semantic: prefer the Class-A oneway-removal fix
    # when it exists so the existing UI continues to surface it as before.
    for f in fixes:
        if f.get("kind") == "remove_false_oneway":
            return f
    # Otherwise, only return a CAGIS-verified fix here when its confidence
    # is high enough to be auto-submittable. Lower-confidence fixes are
    # surfaced by proposed_fixes_for_way() but should not be picked up by
    # legacy callers that expect "this fix is safe to submit".
    high = [f for f in fixes if f.get("confidence", 0) >= HIGH_CONFIDENCE]
    return high[0] if high else None


def proposed_fixes_for_way(
    way: dict,
    *,
    osmose_index: dict[tuple[str, int], list[dict]] | None = None,
) -> list[dict]:
    """Return every applicable proposed fix for a way.

    Combines:
    * Class A/AB heuristic (truthy oneway on residential-class highways).
    * CAGIS-verified oneway disagreement.
    * CAGIS-verified street name disagreement.
    * CAGIS-verified missing-maxspeed.
    * TIGER 2024 fallback name fix (only when CAGIS evidence is absent or
      below ``REVIEW_CONFIDENCE``).
    * TIGER 2024 fallback highway reclass from MTFCC (likewise).

    Each fix dict has ``action``, ``element_type``, ``element_id``,
    ``description``, ``changes`` (or ``tag`` for remove_tag), plus optional
    ``confidence``, ``source_evidence``, ``requires_human_review``, ``kind``.

    When ``osmose_index`` is supplied (from
    :func:`osm.osmose.index_issues_by_osm_id`) every emitted fix is run
    through :func:`osm.osmose.annotate_fixes_with_osmose` before being
    returned, so any way already flagged by Osmose-QA gets ``osmose_match``
    attached and ``requires_human_review`` flipped to ``True``.
    """
    fixes: list[dict] = []
    way_id = way.get("id")
    name_display = way.get("name_display") or way.get("name") or "?"
    cagis = way.get("cagis_match") or None
    confidence = float(cagis.get("confidence", 0.0)) if cagis else 0.0

    evidence = None
    if cagis:
        evidence = {
            "cagis_id": cagis.get("cagis_id"),
            "cagis_name": cagis.get("cagis_name"),
            "cagis_oneway": cagis.get("cagis_oneway"),
            "cagis_speed_limit": cagis.get("cagis_speed_limit"),
            "cagis_functional_class": cagis.get("cagis_functional_class"),
            "confidence": confidence,
            "hausdorff_m": cagis.get("hausdorff_m"),
            "name_similarity": cagis.get("name_similarity"),
        }

    # ------------------------------------------------------------------
    # 1. Heuristic Class A/AB false-oneway fix (preserves original behavior).
    # ------------------------------------------------------------------
    defect = way.get("defect_class")
    if defect in ("A", "AB") and is_oneway_truthy(way.get("oneway")):
        desc = (
            f"Remove false oneway=yes from way {way_id} ({name_display})"
        )
        cagis_confirmed = (
            cagis is not None
            and confidence >= HIGH_CONFIDENCE
            and cagis.get("cagis_oneway") in (None, "", "no")
        )
        if cagis_confirmed and cagis is not None:
            desc += (
                f" (verified against CAGIS centerline "
                f"{cagis.get('cagis_id')}, "
                f"confidence {confidence:.2f})"
            )
        fixes.append({
            "kind": "remove_false_oneway",
            "action": "remove_tag",
            "tag": "oneway",
            "description": desc,
            "element_type": "way",
            "element_id": way_id,
            "changes": {"oneway": None},
            "confidence": confidence if cagis_confirmed else None,
            "source_evidence": evidence if cagis_confirmed else None,
            "requires_human_review": not cagis_confirmed,
        })

    # If CAGIS has nothing useful (or shapely was unavailable), try TIGER
    # 2024 as fallback evidence, then stop here. We still apply the optional
    # Osmose annotation pass so heuristic-only fixes get flagged when
    # Osmose has independently called them out.
    if cagis is None or confidence < REVIEW_CONFIDENCE:
        _maybe_emit_tiger_fixes(way, fixes)
        _apply_osmose_annotation(fixes, osmose_index)
        return fixes

    # ------------------------------------------------------------------
    # 2. CAGIS-verified oneway disagreement (only for ways NOT already
    #    covered by the Class A/AB rule above — those are handled there).
    # ------------------------------------------------------------------
    osm_oneway = (way.get("oneway") or "").strip().lower()
    osm_oneway_truthy = is_oneway_truthy(osm_oneway)
    cagis_oneway = (cagis.get("cagis_oneway") or "no").strip().lower()
    cagis_is_oneway = cagis_oneway in ("yes", "-1")

    already_emitted_oneway = any(
        f.get("kind") == "remove_false_oneway" for f in fixes
    )
    if not already_emitted_oneway:
        if osm_oneway_truthy and not cagis_is_oneway:
            desc = (
                f"Remove oneway tag from way {way_id} ({name_display}) "
                f"(verified against CAGIS centerline "
                f"{cagis.get('cagis_id')}, confidence {confidence:.2f})"
            )
            fixes.append({
                "kind": "remove_oneway_cagis",
                "action": "remove_tag",
                "tag": "oneway",
                "description": desc,
                "element_type": "way",
                "element_id": way_id,
                "changes": {"oneway": None},
                "confidence": confidence,
                "source_evidence": evidence,
                "requires_human_review": confidence < HIGH_CONFIDENCE,
            })
        elif cagis_is_oneway and osm_oneway != cagis_oneway:
            desc = (
                f"Set oneway={cagis_oneway} on way {way_id} ({name_display}) "
                f"(verified against CAGIS centerline "
                f"{cagis.get('cagis_id')}, confidence {confidence:.2f})"
            )
            fixes.append({
                "kind": "set_oneway_cagis",
                "action": "modify_tag",
                "description": desc,
                "element_type": "way",
                "element_id": way_id,
                "changes": {"oneway": cagis_oneway},
                "confidence": confidence,
                "source_evidence": evidence,
                "requires_human_review": confidence < HIGH_CONFIDENCE,
            })

    # ------------------------------------------------------------------
    # 3. CAGIS-verified name fix.
    #
    # Critically, we DO NOT propose replacing spelled-out OSM names
    # ("Woodcreek Drive") with CAGIS-style abbreviations ("WOODCREEK DR").
    # The OSM convention is the spelled-out form; CAGIS uses postal-style
    # shorthand. If the names match after expanding CAGIS abbreviations,
    # nothing needs to change.
    # ------------------------------------------------------------------
    osm_name_norm = norm_name(way.get("name"))
    cagis_name = (cagis.get("cagis_name") or "").strip()
    cagis_name_norm = norm_name(cagis_name)
    name_match_after_expansion = bool(cagis.get("name_match"))
    if (
        cagis_name
        and cagis_name_norm
        and not name_match_after_expansion
        and (
            osm_name_norm is None
            or osm_name_norm != cagis_name_norm
        )
        and confidence >= REVIEW_CONFIDENCE
    ):
        desc = (
            f"Set name='{cagis_name}' on way {way_id} "
            f"(was '{way.get('name') or '(unnamed)'}'; "
            f"verified against CAGIS centerline {cagis.get('cagis_id')}, "
            f"confidence {confidence:.2f})"
        )
        fixes.append({
            "kind": "set_name_cagis",
            "action": "modify_tag",
            "description": desc,
            "element_type": "way",
            "element_id": way_id,
            "changes": {"name": cagis_name},
            "confidence": confidence,
            "source_evidence": evidence,
            # Name canonicalisation is style-sensitive (OSM prefers spelled-out
            # forms, CAGIS uses postal shorthand). Even at high confidence we
            # never auto-submit name changes — they're shown for human review.
            "requires_human_review": True,
        })

    # ------------------------------------------------------------------
    # 4. CAGIS-verified missing maxspeed.
    # ------------------------------------------------------------------
    osm_maxspeed = way.get("maxspeed")
    cagis_speed = cagis.get("cagis_speed_limit")
    if (
        not osm_maxspeed
        and cagis_speed
        and confidence >= REVIEW_CONFIDENCE
    ):
        new_value = f"{cagis_speed} mph"
        desc = (
            f"Set maxspeed={new_value} on way {way_id} ({name_display}) "
            f"(verified against CAGIS centerline "
            f"{cagis.get('cagis_id')}, confidence {confidence:.2f})"
        )
        fixes.append({
            "kind": "set_maxspeed_cagis",
            "action": "modify_tag",
            "description": desc,
            "element_type": "way",
            "element_id": way_id,
            "changes": {"maxspeed": new_value},
            "confidence": confidence,
            "source_evidence": evidence,
            "requires_human_review": confidence < HIGH_CONFIDENCE,
        })

    # NOTE: TIGER fallback fires only when CAGIS evidence is absent or
    # weak (handled in the early-return path above). When we get here, CAGIS
    # already covers this way at REVIEW_CONFIDENCE or higher and TIGER must
    # not override it.

    _apply_osmose_annotation(fixes, osmose_index)
    return fixes


# Confidence at which a TIGER name fix becomes proposable. Higher than the
# generic REVIEW threshold because TIGER is fallback evidence, not primary —
# and TIGER name fixes are always human-review regardless.
TIGER_NAME_CONFIDENCE = 0.85


def _maybe_emit_tiger_fixes(way: dict, fixes: list[dict]) -> None:
    """Append TIGER-verified fixes when CAGIS provides no usable evidence.

    TIGER is fallback evidence, never co-equal with CAGIS:
      * If a high-confidence CAGIS match (>= REVIEW_CONFIDENCE) exists, we
        defer to it entirely and emit no TIGER fixes.
      * If no CAGIS match exists (or it's below the review threshold), we
        emit TIGER fixes at slightly stricter confidence bars and always
        with ``requires_human_review=True``.

    Two TIGER fix kinds are supported:

    1. ``set_name_tiger`` — TIGER ``FULLNAME`` disagrees with OSM ``name``
       at confidence >= 0.85. Always human-review (TIGER, like CAGIS, uses
       postal abbreviations).
    2. ``reclass_highway_tiger`` — TIGER ``MTFCC`` strongly suggests a
       different OSM ``highway`` than what's tagged. The MTFCC -> highway
       mapping lives in :data:`osm.tiger2024.MTFCC_TO_OSM_HIGHWAY`. S1400
       (residential vs unclassified) is intentionally absent from that map
       because the ambiguity is too high to auto-suggest a reclass.
    """
    cagis = way.get("cagis_match") or None
    if cagis is not None:
        cagis_conf = float(cagis.get("confidence", 0.0))
        if cagis_conf >= REVIEW_CONFIDENCE:
            return  # CAGIS already covered this way; defer to it.

    tiger = way.get("tiger_match") or None
    if not tiger:
        return
    confidence = float(tiger.get("confidence", 0.0))
    if confidence < REVIEW_CONFIDENCE:
        return

    way_id = way.get("id")
    name_display = way.get("name_display") or way.get("name") or "?"
    evidence = {
        "tiger_id": tiger.get("tiger_id"),
        "tiger_name": tiger.get("tiger_name"),
        "tiger_mtfcc": tiger.get("tiger_mtfcc"),
        "tiger_rttyp": tiger.get("tiger_rttyp"),
        "confidence": confidence,
        "hausdorff_m": tiger.get("hausdorff_m"),
        "name_similarity": tiger.get("name_similarity"),
    }

    # 5a. TIGER name fix (always human-review).
    osm_name_norm = norm_name(way.get("name"))
    tiger_name = (tiger.get("tiger_name") or "").strip()
    tiger_name_norm = norm_name(tiger_name)
    name_match_after_expansion = bool(tiger.get("name_match"))
    if (
        tiger_name
        and tiger_name_norm
        and not name_match_after_expansion
        and (osm_name_norm is None or osm_name_norm != tiger_name_norm)
        and confidence >= TIGER_NAME_CONFIDENCE
    ):
        desc = (
            f"Set name='{tiger_name}' on way {way_id} "
            f"(was '{way.get('name') or '(unnamed)'}'; "
            f"verified against TIGER/Line 2024 feature "
            f"{tiger.get('tiger_id')}, confidence {confidence:.2f})"
        )
        fixes.append({
            "kind": "set_name_tiger",
            "action": "modify_tag",
            "description": desc,
            "element_type": "way",
            "element_id": way_id,
            "changes": {"name": tiger_name},
            "confidence": confidence,
            "source_evidence": evidence,
            "requires_human_review": True,
        })

    # 5b. Highway reclass from MTFCC (always human-review).
    suggested = _tiger_suggested_highway(tiger.get("tiger_mtfcc"))
    osm_highway = (way.get("highway") or "").strip().lower()
    if (
        suggested
        and suggested != osm_highway
        and confidence >= REVIEW_CONFIDENCE
    ):
        desc = (
            f"Reclassify way {way_id} ({name_display}) from "
            f"highway={osm_highway or '(unset)'} to highway={suggested} "
            f"(MTFCC {tiger.get('tiger_mtfcc')} per TIGER/Line 2024 feature "
            f"{tiger.get('tiger_id')}, confidence {confidence:.2f})"
        )
        fixes.append({
            "kind": "reclass_highway_tiger",
            "action": "modify_tag",
            "description": desc,
            "element_type": "way",
            "element_id": way_id,
            "changes": {"highway": suggested},
            "confidence": confidence,
            "source_evidence": evidence,
            # TIGER class is too coarse for auto-submission.
            "requires_human_review": True,
        })


def _tiger_suggested_highway(mtfcc: str | None) -> str | None:
    """Map a TIGER MTFCC to an OSM highway value.

    Imports lazily so review.py doesn't pull in the shapefile reader at
    module load time.
    """
    if not mtfcc:
        return None
    from osm.tiger2024 import suggested_highway_for_mtfcc
    return suggested_highway_for_mtfcc(mtfcc)


def proposed_fixes_for_finding(finding: dict) -> list[dict]:
    """Emit mechanical fixes for a rider-impact finding that route-diff verified.

    A finding only graduates to a mechanical fix when:

    1. ``finding["route_diff"]["decision"] == 'real'`` (BRouter says routing
       does change with the hypothetical correction), AND
    2. ``finding["kind"]`` is in
       :data:`osm.route_diff.AUTO_FIXABLE_KINDS`.

    Other findings — including ones whose route-diff decision is
    ``'real'`` but whose kind is not auto-fixable — are intentionally
    skipped here and left to the human-review queue.

    Each emitted fix carries a ``source_evidence`` block referencing the
    BRouter decision so changesets can cite it just like CAGIS-verified
    fixes do.
    """
    rd = finding.get("route_diff")
    if not isinstance(rd, dict):
        return []
    if rd.get("decision") != "real":
        return []

    # Local import — avoids importing osm.route_diff (and transitively
    # osm.cache + requests) when nothing in this call needs them.
    from osm.route_diff import AUTO_FIXABLE_KINDS

    kind = finding.get("kind")
    if kind not in AUTO_FIXABLE_KINDS:
        return []

    fid = finding.get("id")
    name_display = finding.get("name") or "(unnamed)"
    evidence = {
        "brouter_decision": rd.get("decision"),
        "brouter_confidence": rd.get("confidence"),
        "delta_pct": rd.get("delta_pct"),
        "before": rd.get("before"),
        "after_predicted": rd.get("after_predicted"),
        "profile": rd.get("profile"),
    }

    if kind == "oneway_minus_one":
        return [{
            "kind": "remove_false_oneway_minus_one",
            "action": "remove_tag",
            "tag": "oneway",
            "description": (
                f"Remove false oneway=-1 from way {fid} ({name_display}); "
                f"BRouter route-diff: routing changes by "
                f"{rd.get('delta_pct'):.1f}% when the tag is hypothetically "
                "removed (decision=real)."
            ),
            "element_type": "way",
            "element_id": fid,
            "changes": {"oneway": None},
            "confidence": rd.get("confidence"),
            "source_evidence": evidence,
            # Even with route-diff confirmation, oneway tag rewrites are
            # high-impact. Keep human in the loop until the harness has
            # proven itself in production.
            "requires_human_review": True,
        }]

    if kind == "oneway_conflict":
        return [{
            "kind": "remove_oneway_conflict",
            "action": "remove_tag",
            "tag": "oneway",
            "description": (
                f"Remove conflicting oneway tag from way {fid} ({name_display}); "
                f"BRouter route-diff: routing changes by "
                f"{rd.get('delta_pct'):.1f}% (decision=real)."
            ),
            "element_type": "way",
            "element_id": fid,
            "changes": {"oneway": None},
            "confidence": rd.get("confidence"),
            "source_evidence": evidence,
            "requires_human_review": True,
        }]

    if kind == "broken_turn_restriction":
        return [{
            "kind": "remove_broken_restriction",
            "action": "remove_relation",
            "description": (
                f"Remove broken turn-restriction relation {fid}; "
                f"BRouter route-diff: routing changes by "
                f"{rd.get('delta_pct'):.1f}% when the restriction is "
                "hypothetically dropped (decision=real)."
            ),
            "element_type": "relation",
            "element_id": fid,
            "changes": None,
            "confidence": rd.get("confidence"),
            "source_evidence": evidence,
            "requires_human_review": True,
        }]

    if kind == "barrier_unqualified":
        return [{
            "kind": "add_access_to_barrier",
            "action": "modify_tag",
            "description": (
                f"Add access=yes to barrier node {fid}; BRouter route-diff "
                f"confirms the barrier wrongly blocks a rider path "
                f"({rd.get('delta_pct'):.1f}% routing change, decision=real)."
            ),
            "element_type": "node",
            "element_id": fid,
            "changes": {"access": "yes"},
            "confidence": rd.get("confidence"),
            "source_evidence": evidence,
            "requires_human_review": True,
        }]

    return []


def _apply_osmose_annotation(
    fixes: list[dict],
    osmose_index: dict[tuple[str, int], list[dict]] | None,
) -> None:
    """Annotate ``fixes`` in place from a pre-built Osmose index.

    Imported lazily so reviewers/changeset callers that don't pass an index
    don't pull in the requests/network transitive surface.
    """
    if not osmose_index or not fixes:
        return
    from osm.osmose import annotate_fixes_with_osmose

    # annotate_fixes_with_osmose takes a list of issues, not the index;
    # the caller already paid the indexing cost so we just rebuild a cheap
    # deduplicated list from the index values.
    seen_uuids: set[str] = set()
    flat_issues: list[dict] = []
    for issue_list in osmose_index.values():
        for iss in issue_list:
            uid = str(iss.get("id"))
            if uid not in seen_uuids:
                seen_uuids.add(uid)
                flat_issues.append(iss)
    annotate_fixes_with_osmose(fixes, flat_issues)


def review_defects(classified: dict) -> list[dict]:
    """Interactive review of all fixable defects. Returns accepted fixes."""
    all_ways = classified["all_ways"]
    fixable = [w for w in all_ways if proposed_fix(w) is not None]

    if not fixable:
        console.print("[yellow]No automatically fixable defects found.[/yellow]")
        return []

    fixable.sort(key=lambda w: (CLASS_ORDER.index(w["defect_class"]), w.get("name_display", "")))

    console.print(f"\n[bold]Found {len(fixable)} fixable defect(s).[/bold]\n")

    mode = Prompt.ask(
        "Review mode",
        choices=["each", "batch-accept", "batch-reject", "quit"],
        default="each",
    )

    if mode == "quit":
        return []
    if mode == "batch-accept":
        batch = [proposed_fix(w) for w in fixable]
        console.print(f"[green]Accepted all {len(batch)} fixes.[/green]")
        return [f for f in batch if f is not None]
    if mode == "batch-reject":
        console.print("[red]Rejected all fixes.[/red]")
        return []

    accepted: list[dict] = []
    for i, w in enumerate(fixable, 1):
        display_issue(w, i, len(fixable))
        if Confirm.ask("  Accept this fix?", default=True):
            fix = proposed_fix(w)
            if fix:
                accepted.append(fix)
                console.print("  [green]Accepted[/green]")
        else:
            console.print("  [red]Skipped[/red]")

    console.print(f"\n[bold]Accepted {len(accepted)} of {len(fixable)} fixes.[/bold]")
    return accepted


def save_review(accepted: list[dict], out_path: Path) -> None:
    """Save accepted fixes to JSON for later submission."""
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(accepted, fh, indent=2, ensure_ascii=False)
    console.print(f"Saved {len(accepted)} accepted fixes to {out_path}")


def load_review(path: Path) -> list[dict]:
    """Load previously saved accepted fixes."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
