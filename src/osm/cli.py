"""Click CLI — scan, fix, auth, report commands."""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import click

from .config import PROJECT_ROOT
from .zones import DEFAULT_ZONE, ZONE_KEYS, ZONES


def _output_dir(zone_key: str) -> Path:
    return PROJECT_ROOT / f"osm-audit-{zone_key}"


def _git_sha_short() -> str:
    """Short git SHA of the working tree, or ``"unknown"`` if not in a repo."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip() or "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


@click.group()
@click.version_option(package_name="osm")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def main(verbose):
    """OSM — TIGER/OSM audit and correction pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


# --- auth ---

@main.group()
def auth():
    """OAuth 2.0 authentication for the OSM API."""
    pass


@auth.command("login")
def auth_login():
    """Run the OAuth 2.0 login flow.

    Reads client_id and client_secret from ~/.config/osm/credentials.json
    """
    from .auth import login
    try:
        login()
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from e


@auth.command("status")
def auth_status():
    """Show current authentication status."""
    from .auth import load_token
    token = load_token()
    if token:
        click.echo(f"Authenticated. Token type: {token.get('token_type', '?')}")
        click.echo(f"Scope: {token.get('scope', '?')}")
    else:
        click.echo("Not authenticated. Run 'osm auth login' to authenticate.")


# --- scan ---

@main.command()
@click.option("--zone", type=click.Choice(ZONE_KEYS + ["all"]), default=DEFAULT_ZONE, help="Zone to audit")
@click.option("--from-cache", is_flag=True, help="Use cached Overpass data instead of live query")
@click.option("--skip-history", is_flag=True, help="Skip revision history analysis (legacy tiger:reviewed=no mode)")
@click.option("--import-only", is_flag=True, help="Only find ways still on original TIGER import version (smaller, high-confidence set)")
@click.option("--with-conflation", is_flag=True, help="Cross-reference every OSM way against CAGIS street centerlines (Hamilton County)")
@click.option("--tiger-only", is_flag=True, help="Skip CAGIS and conflate against TIGER/Line 2024 only (use where CAGIS coverage is incomplete)")
@click.option(
    "--with-route-diff", is_flag=True,
    help=(
        "After detectors run, hit BRouter to test which rider-impact "
        "findings actually change routing. Adds ~1 s per finding "
        "(polite rate limit) and only tests the four kinds we can verify "
        "via routing graph perturbation."
    ),
)
@click.option(
    "--route-diff-profile",
    type=click.Choice(["car-fast", "car-vehicle"]),
    default="car-fast",
    help="BRouter profile to use for the route-diff harness.",
)
@click.option(
    "--include-unnamed-service",
    is_flag=True,
    default=False,
    help=(
        "Include unnamed highway=service ways without a service=* subtype "
        "in Class A. Off by default because these are dominantly interior "
        "parking/driveway circulation that ViaAlgo cannot dispatch into; "
        "enable for exhaustive audits where signal-to-noise is acceptable."
    ),
)
@click.option(
    "--with-gtfs-cross-check/--no-gtfs-cross-check",
    default=True,
    help=(
        "Cross-check the misplaced_bus_stops detector against SORTA's "
        "published GTFS feed. An OSM bus_stop within 30 m of a GTFS stop "
        "is treated as a valid off-curb shelter and suppressed. On by "
        "default; pass --no-gtfs-cross-check to skip the GTFS fetch."
    ),
)
@click.option(
    "--with-bus-route-corroboration/--no-bus-route-corroboration",
    default=True,
    help=(
        "Annotate oneway_conflict findings with transit_corridor=True "
        "when the way lies on a SORTA-published bus-route corridor "
        "(CAGIS Open Data Hub). On by default; --no-bus-route-corroboration "
        "skips the fetch."
    ),
)
def scan(
    zone: str, from_cache: bool, skip_history: bool, import_only: bool,
    with_conflation: bool, tiger_only: bool, with_route_diff: bool,
    route_diff_profile: str, include_unnamed_service: bool,
    with_gtfs_cross_check: bool,
    with_bus_route_corroboration: bool,
):
    """Fetch OSM data, analyse history, classify defects, and generate reports."""
    from rich.progress import Progress

    from .classify import classify
    from .csv_export import write_csvs
    from .dashboard import write_dashboard
    from .fetch import fetch_overpass
    from .history_filter import filter_by_history
    from .xlsx import write_xlsx

    zones_to_run = ZONE_KEYS if zone == "all" else [zone]
    audit_ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    for zk in zones_to_run:
        z = ZONES[zk]
        click.echo(f"\n{'='*50}")
        click.echo(f"  Scanning: {z['name']}")
        click.echo(f"{'='*50}")

        out_dir = _output_dir(zk)

        # Phase 1: Fetch
        query_mode = "import-only (user/timestamp)" if import_only else "tiger:reviewed=no"
        click.echo(f"\nPhase 1: Fetching Overpass data ({query_mode})...")
        raw = fetch_overpass(zk, out_dir, import_only=import_only)

        # Phase 2: History analysis
        click.echo("\nPhase 2: Classifying defects...")
        if include_unnamed_service:
            click.echo("  (unnamed service-oneway ways included in Class A)")

        gtfs_stops_for_classify = None
        if with_gtfs_cross_check:
            try:
                from .gtfs import fetch_sorta_stops
                gtfs_stops_for_classify = fetch_sorta_stops()
                click.echo(
                    f"  SORTA GTFS: loaded {len(gtfs_stops_for_classify):,} "
                    "stop position(s) for bus_stop cross-check"
                )
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    f"  SORTA GTFS fetch failed ({exc}); "
                    "bus_stop cross-check disabled for this scan",
                    err=True,
                )

        bus_routes_for_classify = None
        if with_bus_route_corroboration:
            try:
                from .bus_routes import fetch_bus_routes
                bus_routes_for_classify = fetch_bus_routes()
                click.echo(
                    f"  SORTA bus routes: loaded "
                    f"{len(bus_routes_for_classify):,} polyline(s) "
                    "for oneway_conflict corroboration"
                )
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    f"  SORTA bus-routes fetch failed ({exc}); "
                    "transit-corridor corroboration disabled for this scan",
                    err=True,
                )

        classified = classify(
            raw,
            include_unnamed_service=include_unnamed_service,
            gtfs_stops=gtfs_stops_for_classify,
            bus_routes=bus_routes_for_classify,
        )

        if skip_history:
            click.echo("  History analysis: SKIPPED (legacy mode)")
        else:
            click.echo("\nPhase 2b: Analysing revision history...")
            with Progress() as progress:
                task = progress.add_task("History analysis", total=len(classified["all_ways"]))

                def _progress(done, total, _task=task):
                    progress.update(_task, completed=done)

                filter_by_history(classified["all_ways"], skip_history=False, progress_callback=_progress)

        # Phase 2c: CAGIS conflation (optional)
        run_cagis = with_conflation and not tiger_only
        run_tiger = with_conflation or tiger_only
        if run_cagis:
            click.echo("\nPhase 2c: Conflating against CAGIS centerlines...")
            try:
                from .conflate import (
                    SHAPELY_AVAILABLE,
                    build_index,
                    load_cagis_for_zone,
                )
                from .conflate import (
                    conflate as conflate_fn,
                )
                if not SHAPELY_AVAILABLE:
                    click.echo("  shapely unavailable; skipping conflation.")
                else:
                    cagis = load_cagis_for_zone(zk)
                    click.echo(f"  CAGIS features fetched: {len(cagis):,}")
                    idx = build_index(cagis)
                    conflate_fn(classified["all_ways"], idx)
                    matched = sum(
                        1 for w in classified["all_ways"] if w.get("cagis_match")
                    )
                    classified["summary_stats"]["cagis_features"] = len(cagis)
                    classified["summary_stats"]["cagis_matched"] = matched
                    click.echo(
                        f"  Matched {matched:,} of {len(classified['all_ways']):,} OSM ways"
                    )
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  CAGIS conflation failed: {exc}")

        # Phase 2d: TIGER 2024 fallback conflation. Runs only on ways without
        # a high-confidence CAGIS match (or, in --tiger-only mode, every way).
        if run_tiger:
            click.echo(
                "\nPhase 2d: Conflating against TIGER/Line 2024 (county roads)..."
            )
            try:
                from .tiger2024 import (
                    REVIEW_CONFIDENCE as _TIGER_REV,
                )
                from .tiger2024 import (
                    SHAPELY_AVAILABLE as TIGER_SHAPELY,
                )
                from .tiger2024 import (
                    build_tiger_index,
                    conflate_with_tiger,
                    features_in_bbox,
                    load_tiger2024_features,
                )
                if not TIGER_SHAPELY:
                    click.echo("  shapely unavailable; skipping TIGER.")
                else:
                    tiger_all = load_tiger2024_features()
                    if not tiger_all:
                        click.echo(
                            "  TIGER shapefile unavailable; skipping (CAGIS"
                            " evidence unaffected)."
                        )
                    else:
                        zone_bbox = tuple(ZONES[zk]["bbox"])
                        tiger_zone = features_in_bbox(tiger_all, zone_bbox)
                        click.echo(
                            f"  TIGER features in zone bbox: {len(tiger_zone):,}"
                            f" (of {len(tiger_all):,} county-wide)"
                        )
                        tiger_idx = build_tiger_index(tiger_zone)
                        # Restrict TIGER to ways CAGIS didn't already cover
                        # at high confidence — TIGER is fallback evidence,
                        # not co-equal. In --tiger-only mode, run on all.
                        if tiger_only:
                            unmatched = classified["all_ways"]
                        else:
                            unmatched = [
                                w for w in classified["all_ways"]
                                if not (
                                    w.get("cagis_match")
                                    and w["cagis_match"]["confidence"] >= _TIGER_REV
                                )
                            ]
                        conflate_with_tiger(unmatched, tiger_idx)
                        # Make sure every way has tiger_match=None when not run.
                        for w in classified["all_ways"]:
                            w.setdefault("tiger_match", None)
                        tiger_matched = sum(
                            1 for w in classified["all_ways"] if w.get("tiger_match")
                        )
                        classified["summary_stats"]["tiger_features"] = len(tiger_zone)
                        classified["summary_stats"]["tiger_matched"] = tiger_matched
                        click.echo(
                            f"  TIGER matched (fallback): {tiger_matched:,} of"
                            f" {len(unmatched):,} candidate way(s)"
                        )
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  TIGER conflation failed: {exc}")

        # Phase 2e: Route-diff via BRouter (optional). Promotes rider-impact
        # findings from human-review-only to "decision-tagged" by checking
        # whether a hypothetical fix actually changes routing behaviour.
        if with_route_diff:
            click.echo(
                "\nPhase 2e: Route-diff against BRouter "
                f"(profile={route_diff_profile})..."
            )
            try:
                from .route_diff import (
                    TESTABLE_KINDS,
                    decision_histogram,
                    diff_findings,
                )
                findings = classified.get("extra_findings") or []
                testable = [
                    f for f in findings if f.get("kind") in TESTABLE_KINDS
                ]
                click.echo(
                    f"  {len(testable):,} of {len(findings):,} finding(s) "
                    "are route-diff-testable."
                )
                with Progress() as progress:
                    task = progress.add_task(
                        "Route-diff", total=len(testable),
                    )

                    def _rd_progress(done, total, _task=task):
                        progress.update(_task, completed=done)

                    diff_findings(
                        testable,
                        classified["all_ways"],
                        profile=route_diff_profile,
                        progress_callback=_rd_progress,
                    )
                hist = decision_histogram(testable)
                classified.setdefault("summary_stats", {})
                classified["summary_stats"]["route_diff_decisions"] = hist
                classified["summary_stats"]["route_diff_profile"] = (
                    route_diff_profile
                )
                click.echo(
                    f"  Decisions: real={hist['real']}, "
                    f"inconclusive={hist['inconclusive']}, "
                    f"noisy={hist['noisy']}, untested={hist['untested']}"
                )
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  Route-diff failed: {exc}")

        # Phase 3: Reports
        click.echo("\nPhase 3: Generating reports...")
        zone_name_hyphen = z["name"].replace(" / ", "-").replace(" ", "-")

        from .fetch import overpass_query
        query_text = overpass_query(z["bbox"], import_only=import_only)

        xlsx_path = out_dir / "reports" / f"OSM-Audit-{zone_name_hyphen}.xlsx"
        write_xlsx(classified, zk, xlsx_path, query_text, audit_ts, output_root=PROJECT_ROOT)

        dash_path = out_dir / "reports" / f"OSM-Audit-{zone_name_hyphen}-Dashboard.html"
        write_dashboard(classified, zk, z["name"], dash_path, audit_ts)

        csv_dir = out_dir / "csv"
        write_csvs(classified, csv_dir)

        # Save scan results for later fix/report commands
        results_path = out_dir / "scan-results.json"
        _save_scan_results(classified, results_path)

        # Summary
        stats = classified["summary_stats"]
        click.echo(f"\n{'='*50}")
        click.echo(f"  OSM Audit Complete: {z['name']}")
        click.echo(f"  Date: {audit_ts}")
        click.echo(f"{'='*50}")
        click.echo(f"  Total unreviewed segments:    {stats['total']:,}")
        click.echo(f"  Residential (unreviewed):     {stats['residential']:,}")
        click.echo(f"  Class A (false one-way):      {stats['class_a_count']:,}")
        click.echo(f"  Class B (multi-segment):      {stats['class_b_way_count']:,}")
        click.echo(f"  Class AB (compound):          {stats['class_ab_count']:,}")
        click.echo(f"  Node gaps detected:           {stats['gaps_found']:,}")
        click.echo(f"{'─'*50}")
        click.echo(f"  Files saved to: {out_dir}")
        click.echo(f"{'='*50}")


# --- fix ---

@main.command()
@click.option("--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE, help="Zone to fix")
@click.option("--dry-run", is_flag=True, help="Preview fixes without submitting")
@click.option(
    "--annotate-fixes",
    is_flag=True,
    default=False,
    help=(
        "Cross-reference Osmose-QA before review: any fix targeting a way "
        "already flagged by Osmose is marked human-review and gets an "
        "osmose_match descriptor."
    ),
)
@click.option(
    "--with-route-impact",
    is_flag=True,
    default=False,
    help=(
        "On dry-run only: run BRouter route-impact for the accepted "
        "set_oneway_cagis / remove_oneway_cagis fixes and print the "
        "value-story summary inline (\"this batch will change N "
        "MetroNow-relevant routes by avg X%\"). Adds ~1 sec per oneway "
        "fix (polite-rate-limit). Skipped on non-dry-run runs because "
        "the actual submission path doesn't need it."
    ),
)
def fix(
    zone: str, dry_run: bool, annotate_fixes: bool, with_route_impact: bool,
):
    """Review and submit corrections to OSM."""
    from .changeset import submit_fixes
    from .review import review_defects

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first.")
        raise SystemExit(1)

    classified = _load_scan_results(results_path)

    if annotate_fixes:
        try:
            from .osmose import (
                annotate_fixes_with_osmose,
                fetch_issues_for_zone,
            )
            from .review import proposed_fixes_for_way
            issues = fetch_issues_for_zone(zone)
            click.echo(f"  Osmose issues fetched: {len(issues):,}")
            for w in classified.get("all_ways", []):
                fixes_for_way = proposed_fixes_for_way(w)
                if not fixes_for_way:
                    continue
                annotate_fixes_with_osmose(fixes_for_way, issues)
                # Stash the annotated osmose hits onto the way so the
                # interactive UI surfaces them downstream.
                hits = [
                    f["osmose_match"]
                    for f in fixes_for_way
                    if "osmose_match" in f
                ]
                if hits:
                    w["osmose_matches"] = hits
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  Osmose annotation failed: {exc}")

    accepted = review_defects(classified)

    if not accepted:
        click.echo("No fixes to submit.")
        return

    z = ZONES[zone]
    comment = f"Fix false oneway=yes on residential streets in {z['name']} (TIGER audit)"

    # Phase 4b inline value-story payload — only for dry-run, only for
    # oneway fixes (the kinds that perturb the routing graph). Maxspeed
    # / name fixes don't move BRouter routes, so they're skipped with
    # an explicit reason in the summary.
    if with_route_impact and dry_run:
        from rich.progress import Progress

        from .route_diff import (
            ONEWAY_FIX_KINDS,
            route_impact_for_fixes,
            summarize_route_impact,
        )

        oneway_fixes = [f for f in accepted if f.get("kind") in ONEWAY_FIX_KINDS]
        if not oneway_fixes:
            click.echo(
                "[ROUTE-IMPACT] No oneway fixes in this batch — "
                "set_maxspeed_cagis / set_name_cagis don't perturb routing."
            )
        else:
            click.echo(
                f"[ROUTE-IMPACT] Running BRouter route-diff on "
                f"{len(oneway_fixes):,} oneway fix(es)..."
            )
            with Progress() as progress:
                task = progress.add_task(
                    "Route-impact", total=len(oneway_fixes),
                )

                def _progress(done, total, _task=task):
                    progress.update(_task, completed=done)

                route_impact_for_fixes(
                    oneway_fixes,
                    classified.get("all_ways", []),
                    progress_callback=_progress,
                )
            summary = summarize_route_impact(oneway_fixes)
            click.echo(
                f"[ROUTE-IMPACT] real={summary['real']}, "
                f"inconclusive={summary['inconclusive']}, "
                f"noisy={summary['noisy']}, skipped={summary['fixes_skipped']}"
            )
            if summary["real"]:
                click.echo(
                    f"[ROUTE-IMPACT] Of the {summary['real']} fixes that "
                    "change routing meaningfully: "
                    f"avg delta {summary['avg_delta_pct_real']}% of route "
                    f"cost, max {summary['max_delta_pct_real']}%, "
                    f"avg duration shift {summary['avg_duration_delta_s_real']} s."
                )
    elif with_route_impact and not dry_run:
        click.echo(
            "--with-route-impact ignored on non-dry-run; the harness is "
            "for previewing impact before submission, not for the "
            "submission itself.",
            err=True,
        )

    result = submit_fixes(accepted, comment, dry_run=dry_run)

    if result.get("dry_run"):
        click.echo(f"\n[DRY RUN] {result['fixes_applied']} fix(es) would be submitted.")
    elif result.get("changeset_id"):
        click.echo(
            f"\nChangeset {result['changeset_id']}: "
            f"{result['fixes_applied']} fix(es) applied."
        )
        click.echo(f"https://www.openstreetmap.org/changeset/{result['changeset_id']}")


# --- conflate ---

@main.command()
@click.option("--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE, help="Zone to conflate")
@click.option("--force-refresh", is_flag=True, help="Re-fetch CAGIS data even if a fresh cache exists")
@click.option(
    "--baseline-manifest",
    is_flag=True,
    help="Phase 2a: also write per-way diagnostic manifest "
         "(cagis_baseline_<gitsha>.json) with F1-F4 bucket attribution.",
)
def conflate(zone: str, force_refresh: bool, baseline_manifest: bool):
    """Conflate the most recent scan against CAGIS street centerlines.

    Reads ``scan-results.json`` for ``--zone``, loads the CAGIS centerlines
    for that zone (cached locally for 90 days), runs the spatial match,
    and rewrites ``scan-results.json`` with ``cagis_match`` attached to
    every way. The web UI picks the new fields up automatically.

    With ``--baseline-manifest``, additionally write a diagnostic manifest
    classifying every way's match outcome into MATCHED_HIGH / MATCHED_REVIEW
    / F1_NO_CANDIDATE / F2_NAME_FAIL / F3_GEOMETRY_FAIL / F4_DIRECTION_DRAG
    / MIXED_LOW. Used to attribute the 8.7% match rate to specific failure
    modes before tuning weights. Read-only — does not change scoring.

    Source: CAGIS Open Data Hub, Hamilton County, Ohio.
    """
    from .conflate import (
        SHAPELY_AVAILABLE,
        build_index,
        diagnose_all,
        load_cagis_for_zone,
        write_baseline_manifest,
    )
    from .conflate import conflate as conflate_fn

    if not SHAPELY_AVAILABLE:
        click.echo(
            "shapely is not installed; conflation cannot run. "
            "Install with: pip install 'shapely>=2.0'",
            err=True,
        )
        raise SystemExit(1)

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(
            f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first."
        )
        raise SystemExit(1)

    classified = _load_scan_results(results_path)
    click.echo(f"Loaded {len(classified.get('all_ways', [])):,} OSM ways from scan.")

    cagis = load_cagis_for_zone(zone, force_refresh=force_refresh)
    click.echo(f"CAGIS features fetched: {len(cagis):,}")

    idx = build_index(cagis)
    conflate_fn(classified["all_ways"], idx)
    matched = sum(1 for w in classified["all_ways"] if w.get("cagis_match"))

    classified.setdefault("summary_stats", {})
    classified["summary_stats"]["cagis_features"] = len(cagis)
    classified["summary_stats"]["cagis_matched"] = matched

    _save_scan_results(classified, results_path)
    click.echo(
        f"Matched {matched:,} of {len(classified['all_ways']):,} OSM ways"
        " against CAGIS centerlines."
    )
    click.echo(f"Updated {results_path}")

    if baseline_manifest:
        git_sha = _git_sha_short()
        rows = diagnose_all(classified["all_ways"], idx)
        manifest_dir = _output_dir(zone) / "data"
        manifest_path = manifest_dir / f"cagis_baseline_{git_sha}.json"
        summary = write_baseline_manifest(
            rows,
            zone_key=zone,
            git_sha=git_sha,
            out_path=manifest_path,
        )
        click.echo(
            f"Phase 2a baseline manifest: {manifest_path}\n"
            f"  match_rate={summary['match_rate_pct']}%  "
            f"auto_submit={summary['auto_submit_rate_pct']}%\n"
            f"  buckets={summary['buckets']}"
        )


# --- conflate-tiger ---

@main.command(name="conflate-tiger")
@click.option(
    "--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE,
    help="Zone to conflate against TIGER/Line 2024",
)
@click.option(
    "--force-refresh", is_flag=True,
    help="Re-download the TIGER 2024 ZIP instead of using the local cache",
)
@click.option(
    "--all-ways", is_flag=True,
    help="Conflate every way (default: skip ways with high-confidence CAGIS)",
)
def conflate_tiger(zone: str, force_refresh: bool, all_ways: bool):
    """Conflate the most recent scan against TIGER/Line 2024.

    By default this only annotates ways that don't already have a
    high-confidence CAGIS match (TIGER is fallback evidence). Pass
    ``--all-ways`` to run TIGER on every way regardless.

    Source: U.S. Census Bureau, TIGER/Line Shapefiles 2024 (public domain).
    """
    from .tiger2024 import (
        REVIEW_CONFIDENCE as TIGER_REV,
    )
    from .tiger2024 import (
        SHAPELY_AVAILABLE,
        build_tiger_index,
        conflate_with_tiger,
        features_in_bbox,
        load_tiger2024_features,
    )

    if not SHAPELY_AVAILABLE:
        click.echo(
            "shapely is not installed; TIGER conflation cannot run.", err=True,
        )
        raise SystemExit(1)

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(
            f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first."
        )
        raise SystemExit(1)

    classified = _load_scan_results(results_path)
    click.echo(f"Loaded {len(classified.get('all_ways', [])):,} OSM ways from scan.")

    tiger_all = load_tiger2024_features(force_refresh=force_refresh)
    if not tiger_all:
        click.echo("TIGER shapefile unavailable; aborting.", err=True)
        raise SystemExit(1)
    zone_bbox = tuple(ZONES[zone]["bbox"])
    tiger_zone = features_in_bbox(tiger_all, zone_bbox)
    click.echo(
        f"TIGER features in {zone} bbox: {len(tiger_zone):,}"
        f" (of {len(tiger_all):,} county-wide)"
    )
    tiger_idx = build_tiger_index(tiger_zone)

    if all_ways:
        unmatched = classified["all_ways"]
    else:
        unmatched = [
            w for w in classified["all_ways"]
            if not (
                w.get("cagis_match")
                and w["cagis_match"]["confidence"] >= TIGER_REV
            )
        ]
    conflate_with_tiger(unmatched, tiger_idx)
    for w in classified["all_ways"]:
        w.setdefault("tiger_match", None)

    matched = sum(1 for w in classified["all_ways"] if w.get("tiger_match"))
    classified.setdefault("summary_stats", {})
    classified["summary_stats"]["tiger_features"] = len(tiger_zone)
    classified["summary_stats"]["tiger_matched"] = matched

    _save_scan_results(classified, results_path)
    click.echo(
        f"TIGER matched {matched:,} of {len(unmatched):,} candidate way(s)."
    )
    click.echo(f"Updated {results_path}")


# --- route-diff ---

@main.command(name="route-diff")
@click.option(
    "--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE,
    help="Zone whose scan-results.json to test",
)
@click.option(
    "--profile",
    type=click.Choice(["car-fast", "car-vehicle"]),
    default="car-fast",
    help="BRouter profile to use.",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    help=(
        "Cap the number of testable findings to test in this run "
        "(0 = no cap). BRouter is rate-limited at 1 sec/call by default; "
        "use this to keep batches short during exploration."
    ),
)
def route_diff_cmd(zone: str, profile: str, limit: int):
    """Run BRouter route-diff against the most recent scan-results.json.

    Tests every rider-impact finding whose kind is in
    :data:`osm.route_diff.TESTABLE_KINDS` and writes the augmented
    findings (each with a ``route_diff`` key) back to
    ``osm-audit-{zone}/scan-results.json``.

    BRouter source: https://brouter.de/brouter (GPL engine over OSM data).
    """
    from rich.progress import Progress

    from .route_diff import (
        TESTABLE_KINDS,
        decision_histogram,
        diff_findings,
        graduate_findings,
    )

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(
            f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first."
        )
        raise SystemExit(1)

    classified = _load_scan_results(results_path)
    findings = classified.get("extra_findings") or []
    testable = [f for f in findings if f.get("kind") in TESTABLE_KINDS]
    if limit and limit > 0:
        testable = testable[:limit]
    click.echo(
        f"Loaded {len(findings):,} finding(s); testing {len(testable):,} "
        "via BRouter route-diff."
    )

    with Progress() as progress:
        task = progress.add_task("Route-diff", total=len(testable))

        def _progress(done, total, _task=task):
            progress.update(_task, completed=done)

        diff_findings(
            testable,
            classified["all_ways"],
            profile=profile,
            progress_callback=_progress,
        )

    hist = decision_histogram(testable)
    graduated, human = graduate_findings(testable)
    classified.setdefault("summary_stats", {})
    classified["summary_stats"]["route_diff_decisions"] = hist
    classified["summary_stats"]["route_diff_profile"] = profile

    _save_scan_results(classified, results_path)

    click.echo(
        f"Decisions: real={hist['real']}, inconclusive={hist['inconclusive']}, "
        f"noisy={hist['noisy']}, untested={hist['untested']}"
    )
    click.echo(
        f"Graduated to mechanical fix: {len(graduated):,}; "
        f"stay human-review: {len(human):,}."
    )
    click.echo(f"Updated {results_path}")


# --- fix-impact ---

@main.command(name="fix-impact")
@click.option(
    "--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE,
    help="Zone whose CAGIS-verified oneway fixes to measure",
)
@click.option(
    "--profile",
    type=click.Choice(["car-fast", "car-vehicle"]),
    default="car-fast",
    help="BRouter profile to use.",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    help=(
        "Cap the number of fixes to measure (0 = no cap). BRouter is "
        "rate-limited at ~1 sec/call; a full Blue Ash batch (~480 oneway "
        "fixes) takes ~8 minutes. Use this to keep exploration batches short."
    ),
)
def fix_impact(zone: str, profile: str, limit: int):
    """Phase 4b — measure routing impact of CAGIS-verified oneway fixes.

    Reads the most recent scan-results.json, finds every fix descriptor
    with kind in ``ONEWAY_FIX_KINDS`` (set_oneway_cagis,
    remove_oneway_cagis), runs BRouter route-diff for each one, and
    prints the value-story summary that downstream stakeholders care
    about — "this batch will change N MetroNow-relevant routes by avg
    X%". Writes the augmented fix list (each fix gets a ``route_impact``
    key) back to scan-results.json so the web UI can surface it.

    Useful before submitting a batch of CAGIS-verified oneway fixes —
    confirms the fixes actually move BRouter routes, not just OSM tags.
    Decision threshold: a fix is "real" when its delta exceeds 15% of
    the live route's cost; "noisy" below 3%; "inconclusive" between.
    """
    from rich.progress import Progress

    from .review import proposed_fixes_for_way
    from .route_diff import (
        ONEWAY_FIX_KINDS,
        route_impact_for_fixes,
        summarize_route_impact,
    )

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(
            f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first."
        )
        raise SystemExit(1)

    classified = _load_scan_results(results_path)
    # Non-interactive collection: walk every classified way and emit the
    # CAGIS-verified oneway fixes directly. fix-impact must not block on
    # user review — its purpose is to produce the summary that *informs*
    # the review.
    oneway_fixes: list[dict] = []
    for w in classified.get("all_ways", []):
        for f in proposed_fixes_for_way(w):
            if f.get("kind") in ONEWAY_FIX_KINDS:
                oneway_fixes.append(f)
    if not oneway_fixes:
        click.echo(
            f"No CAGIS-verified oneway fixes for {zone}. "
            "Run 'osm conflate --zone <key>' first."
        )
        return

    if limit and limit > 0:
        oneway_fixes = oneway_fixes[:limit]
    click.echo(
        f"Loaded {len(oneway_fixes):,} CAGIS-verified oneway fix(es); "
        "running BRouter route-diff."
    )

    with Progress() as progress:
        task = progress.add_task("Route-impact", total=len(oneway_fixes))

        def _progress(done, total, _task=task):
            progress.update(_task, completed=done)

        route_impact_for_fixes(
            oneway_fixes,
            classified.get("all_ways", []),
            profile=profile,
            progress_callback=_progress,
        )

    summary = summarize_route_impact(oneway_fixes)
    classified.setdefault("summary_stats", {})
    classified["summary_stats"]["route_impact"] = summary
    classified["summary_stats"]["route_impact_profile"] = profile

    _save_scan_results(classified, results_path)

    click.echo(
        f"Routing impact: real={summary['real']}, "
        f"inconclusive={summary['inconclusive']}, noisy={summary['noisy']}, "
        f"skipped={summary['fixes_skipped']}"
    )
    if summary["real"]:
        click.echo(
            f"Of the {summary['real']} fixes that change routing meaningfully: "
            f"avg delta {summary['avg_delta_pct_real']}% of route cost, "
            f"max {summary['max_delta_pct_real']}%, "
            f"avg duration shift {summary['avg_duration_delta_s_real']} s."
        )
    click.echo(f"Updated {results_path}")


# --- baseline-diff ---

@main.command(name="baseline-diff")
@click.option(
    "--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE,
    help="Zone whose baseline manifests to diff",
)
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to the OLDER manifest. Defaults to the second-newest "
        "cagis_baseline_*.json under osm-audit-{zone}/data/."
    ),
)
@click.option(
    "--to",
    "to_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to the NEWER manifest. Defaults to the newest "
        "cagis_baseline_*.json under osm-audit-{zone}/data/."
    ),
)
def baseline_diff_cmd(zone: str, from_path: str | None, to_path: str | None):
    """Compare two CAGIS baseline manifests and surface bucket shifts.

    Use this after a code change to the matcher OR after a quarterly
    CAGIS data refresh to confirm the asymmetric promotion criterion
    held: MATCHED_HIGH should rise from F3 reductions, not from
    MATCHED_REVIEW contractions; total_ways should be stable across
    runs.

    Without --from / --to, defaults to the two newest manifests in
    osm-audit-{zone}/data/.
    """
    from pathlib import Path as _Path

    from .conflate import (
        diff_baselines,
        load_baseline_manifest,
        newest_two_manifests,
    )

    if from_path and to_path:
        a_path, b_path = _Path(from_path), _Path(to_path)
    else:
        pair = newest_two_manifests(_output_dir(zone) / "data")
        if pair is None:
            click.echo(
                f"Need at least 2 cagis_baseline_*.json under "
                f"osm-audit-{zone}/data/ — run 'osm conflate --zone {zone} "
                "--baseline-manifest' twice (across separate code changes)."
            )
            raise SystemExit(1)
        a_path, b_path = pair

    a_doc = load_baseline_manifest(a_path)
    b_doc = load_baseline_manifest(b_path)
    diff = diff_baselines(a_doc, b_doc)

    click.echo(f"Diff: {a_path.name}  →  {b_path.name}")
    click.echo(f"Zone: {diff['zone_key']}")
    click.echo(f"SHA:  {diff['git_sha_a']}  →  {diff['git_sha_b']}")
    click.echo("")

    # Headline
    def _fmt(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    if diff["headline"]:
        click.echo("Headline:")
        for k, vals in diff["headline"].items():
            a, b, d = vals.get("a"), vals.get("b"), vals.get("delta")
            if isinstance(d, float):
                d_str = f" ({d:+.2f})"
            elif isinstance(d, int):
                d_str = f" ({d:+d})"
            else:
                d_str = ""
            click.echo(
                f"  {k:30s} {_fmt(a):>10s} → {_fmt(b):>10s}{d_str}"
            )
        click.echo("")

    # Buckets
    click.echo("Buckets:")
    for bucket, vals in diff["buckets"].items():
        a, b, d, dp = vals["a"], vals["b"], vals["delta"], vals["delta_pct"]
        sign = " " if d == 0 else ("+" if d > 0 else "−")
        click.echo(
            f"  {bucket:25s} {a:>6d} → {b:>6d}  "
            f"{sign}{abs(d):>6d}  ({dp:+6.1f}%)"
        )
    click.echo("")

    if diff["alerts"]:
        click.echo("ALERTS:")
        for a in diff["alerts"]:
            click.echo(f"  ! {a}")
    else:
        click.echo("No promotion-criterion or scope alerts.")


# --- maproulette ---

@main.command(name="maproulette")
@click.option(
    "--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE,
    help="Zone whose unverified candidates to export",
)
@click.option(
    "--kind",
    type=click.Choice(["class-a", "gaps", "both"]),
    default="class-a",
    help=(
        "Which challenge to generate. class-a = Class A/AB ways below "
        "the CAGIS auto-submit threshold (default). gaps = node-disconnect "
        "candidates. both = produce two separate .geojsonl files plus two "
        "separate metadata payloads."
    ),
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help=(
        "Output path for a single-kind challenge file. Defaults to "
        "osm-audit-{zone}/maproulette/{zone}-{kind}.geojsonl. Ignored "
        "when --kind=both."
    ),
)
def maproulette_cmd(zone: str, kind: str, out: str | None):
    """Phase 3 — generate MapRoulette challenges for human-review queues.

    Two challenge kinds:

    \b
    * class-a — Class A/AB ways that did NOT make the auto-submit pool
      (no CAGIS match at HIGH_CONFIDENCE). Each task asks a mapper to
      verify whether the way's `oneway=yes` tag is a TIGER artefact.
    * gaps — same-named OSM ways within 30 m of each other but with no
      shared node. Each task asks a mapper to confirm and join.

    Use --kind=both to write both files in a single invocation.
    """
    from pathlib import Path as _Path

    from .maproulette import (
        build_gap_tasks,
        build_tasks,
        challenge_metadata,
        gap_challenge_metadata,
        unverified_class_a_ways,
        unverified_gaps,
        write_gap_geojsonl,
        write_geojsonl,
    )

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(
            f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first."
        )
        raise SystemExit(1)

    classified = _load_scan_results(results_path)
    zone_name = ZONES[zone].get("name", zone)

    def _write_class_a():
        ways = unverified_class_a_ways(classified)
        tasks = build_tasks(ways)
        if not tasks:
            click.echo(
                f"No Class A / AB unverified ways for {zone}. The auto-submit "
                "pool may already cover the candidates, or the polygon clip is "
                "too tight."
            )
            return
        out_path = (
            _Path(out) if (out and kind == "class-a")
            else _output_dir(zone) / "maproulette"
            / f"{zone}-class-a-unverified.geojsonl"
        )
        n = write_geojsonl(tasks, out_path)
        meta = challenge_metadata(
            zone_name=zone_name, zone_key=zone, n_tasks=n,
        )
        click.echo(f"Wrote {n:,} Class A/AB task(s) to {out_path}")
        click.echo("")
        click.echo("Suggested challenge metadata (paste into MapRoulette UI):")
        click.echo(json.dumps(meta, indent=2, ensure_ascii=False))

    def _write_gaps():
        gaps = unverified_gaps(classified)
        tasks = build_gap_tasks(gaps)
        if not tasks:
            click.echo(f"No node-disconnect gap candidates for {zone}.")
            return
        out_path = (
            _Path(out) if (out and kind == "gaps")
            else _output_dir(zone) / "maproulette"
            / f"{zone}-gaps.geojsonl"
        )
        n = write_gap_geojsonl(tasks, out_path)
        meta = gap_challenge_metadata(
            zone_name=zone_name, zone_key=zone, n_tasks=n,
        )
        click.echo(f"Wrote {n:,} node-disconnect task(s) to {out_path}")
        click.echo("")
        click.echo("Suggested gap-challenge metadata (paste into MapRoulette UI):")
        click.echo(json.dumps(meta, indent=2, ensure_ascii=False))

    if kind in ("class-a", "both"):
        _write_class_a()
        if kind == "both":
            click.echo("")
    if kind in ("gaps", "both"):
        _write_gaps()


# --- transit-status / transit-budget ---

@main.command(name="transit-status")
def transit_status_cmd():
    """Show Transit App API client health (no network calls).

    Prints whether the key file is present, monthly-quota usage,
    budget-cap headroom, and the cache directory location. Safe to
    run at any time — never makes a network call.
    """
    from .transit import (
        CACHE_DIR,
        KEY_FILE,
        POWERED_BY_TRANSIT_ATTRIBUTION,
        QUOTA_BUDGET_FRACTION,
        RATE_LIMIT_PER_MINUTE,
        USAGE_FILE,
        status,
    )

    s = status()
    click.echo("Transit App API — client status")
    click.echo("")
    click.echo(f"  Key file:        {KEY_FILE}")
    click.echo(f"  Has API key:     {'yes' if s.has_key else 'NO — set ~/.config/osm/transit_api.json'}")
    click.echo(f"  Usage file:      {USAGE_FILE}")
    click.echo(f"  Monthly quota:   {s.monthly_quota:,} calls (free tier)")
    click.echo(
        f"  Used this month: {s.used_this_month:,} / "
        f"{s.budget_cap:,} budget cap "
        f"({QUOTA_BUDGET_FRACTION:.0%} of quota)"
    )
    remaining = max(0, s.budget_cap - s.used_this_month)
    click.echo(f"  Remaining:       {remaining:,} calls before client refuses")
    click.echo(f"  Quota exhausted: {'YES' if s.quota_exhausted else 'no'}")
    click.echo(f"  Rate limit:      {RATE_LIMIT_PER_MINUTE} calls/minute")
    click.echo(f"  Cache dir:       {CACHE_DIR} ({'exists' if s.cache_dir_exists else 'will be created on first call'})")
    click.echo("")
    click.echo("  Required attribution wherever Transit data is shown:")
    click.echo(f"    {POWERED_BY_TRANSIT_ATTRIBUTION!r} (verbatim, per Transit ToS §3.2)")


@main.command(name="transit-budget")
@click.option(
    "--calls", type=int, default=None,
    help="Hypothetical number of calls — report whether it fits in remaining budget",
)
@click.option(
    "--per-day", is_flag=True,
    help="Print suggested per-day cap to land at exactly 100%% of budget by month-end",
)
def transit_budget_cmd(calls: int | None, per_day: bool):
    """Plan Transit API usage against the remaining monthly budget.

    Default: print remaining headroom and a recommended per-day pacing
    figure so the budget lasts the rest of the month.

    With --calls N: report whether a hypothetical N-call run fits in the
    remaining budget and what fraction of headroom it would consume.
    Exits with status 1 if N exceeds the remaining budget.
    """
    from calendar import monthrange

    from .transit import status

    s = status()
    remaining = max(0, s.budget_cap - s.used_this_month)
    today = dt.datetime.now(dt.UTC)
    _, days_in_month = monthrange(today.year, today.month)
    days_left = max(1, days_in_month - today.day + 1)

    click.echo("Transit App API — budget calculator")
    click.echo("")
    click.echo(f"  Used:        {s.used_this_month:,} / {s.budget_cap:,}")
    click.echo(f"  Remaining:   {remaining:,} calls")
    click.echo(
        f"  Days left:   {days_left} (of {days_in_month}; rollover on the 1st)"
    )

    if per_day or calls is None:
        per_day_cap = remaining // days_left if days_left else remaining
        click.echo(
            f"  Per-day cap: {per_day_cap:,} calls/day to land at 100% of budget"
        )

    if calls is not None:
        if calls <= 0:
            click.echo("  --calls must be > 0", err=True)
            raise SystemExit(2)
        fits = calls <= remaining
        pct = (calls / remaining * 100.0) if remaining else float("inf")
        click.echo("")
        click.echo(f"  Hypothetical: {calls:,} calls")
        if fits:
            click.echo(
                f"  → Fits. Consumes {pct:.1f}% of remaining budget; "
                f"{remaining - calls:,} calls would still be available."
            )
        else:
            shortfall = calls - remaining
            click.echo(
                f"  → DOES NOT FIT. Short by {shortfall:,} calls "
                f"({pct:.1f}% of remaining). Wait for the next month or "
                f"request a quota uplift before running."
            )
            raise SystemExit(1)


# --- motis-status ---

@main.command(name="motis-status")
@click.option(
    "--probe/--no-probe",
    default=True,
    help="Send a one-shot /api/v5/plan request to verify the instance "
         "answers; --no-probe just prints the configured base URL.",
)
def motis_status_cmd(probe: bool):
    """Show MOTIS routing-engine reachability (prototype).

    The MOTIS client is opt-in. Set MOTIS_BASE to point at a hosted or
    self-managed instance; with --probe (default) this command sends a
    trivial /api/v5/plan request to confirm reachability before any
    pipeline component tries to use it.

    See docs/motis-deployment.md for stand-up notes.
    """
    from .motis import MOTIS_DEFAULT_BASE, _base_url, is_available

    base = _base_url()
    click.echo(f"MOTIS base URL: {base}")
    if base == MOTIS_DEFAULT_BASE:
        click.echo("  (default; set MOTIS_BASE to override)")
    if not probe:
        return
    click.echo("Probing /api/v5/plan…")
    if is_available():
        click.echo("  → MOTIS is reachable and answering /api/v5/plan.")
    else:
        click.echo(
            "  → MOTIS not reachable. The pipeline will continue using "
            "BRouter; see docs/motis-deployment.md for setup."
        )
        raise SystemExit(1)


# --- preflight ---

_PREFLIGHT_GLYPH = {
    "PASS": "✓",
    "FAIL": "✗",
    "WARN": "⚠",
    "MANUAL": "☐",
}


@main.command()
@click.option(
    "--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE,
    help="Zone whose first-changeset readiness to verify",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Treat WARN as a non-zero exit (default: only FAIL is non-zero)",
)
@click.option(
    "--skip-pytest",
    is_flag=True,
    help="Skip the pytest run (faster, but the test-suite gate is not enforced)",
)
def preflight(zone: str, strict: bool, skip_pytest: bool):
    """Pre-flight readiness for the first live changeset.

    Codifies the codable items of docs/community-prep/04-pre-flight-checklist.md
    and surfaces the human-attestation items as MANUAL so nothing slips
    through the cracks on the day of the first submission.

    Exit codes:

    \b
        0  No FAIL (and no WARN if --strict)
        1  At least one FAIL
        2  At least one WARN with --strict
    """
    from .preflight import (
        CAT_ACCOUNT,
        CAT_COMMUNITY,
        CAT_FIX,
        CAT_MONITORING,
        CAT_PIPELINE,
        CAT_SCAN,
        run_preflight,
    )

    report_obj = run_preflight(zone, run_pytest=not skip_pytest)

    click.echo(f"Pre-flight check — zone: {zone}")
    click.echo("")

    category_order = [
        CAT_COMMUNITY,
        CAT_ACCOUNT,
        CAT_PIPELINE,
        CAT_SCAN,
        CAT_FIX,
        CAT_MONITORING,
    ]
    by_cat: dict[str, list] = {cat: [] for cat in category_order}
    for c in report_obj.checks:
        by_cat.setdefault(c.category, []).append(c)

    for cat in category_order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        click.echo(f"{cat}")
        click.echo("-" * len(cat))
        for c in items:
            glyph = _PREFLIGHT_GLYPH.get(c.status, "?")
            click.echo(f"  {glyph} [{c.status:<6}] {c.name}")
            if c.detail:
                click.echo(f"             {c.detail}")
        click.echo("")

    click.echo(
        f"Summary: {report_obj.n_pass} PASS · "
        f"{report_obj.n_fail} FAIL · "
        f"{report_obj.n_warn} WARN · "
        f"{report_obj.n_manual} MANUAL"
    )
    if report_obj.n_manual:
        click.echo(
            "  (MANUAL items require human attestation — the checklist "
            "exists to keep them visible, not to auto-clear them.)"
        )

    raise SystemExit(report_obj.exit_code(strict=strict))


# --- report ---

@main.command()
@click.option("--zone", type=click.Choice(ZONE_KEYS), default=DEFAULT_ZONE, help="Zone to report")
def report(zone: str):
    """Regenerate reports from the last scan."""
    from .csv_export import write_csvs
    from .dashboard import write_dashboard
    from .fetch import overpass_query
    from .xlsx import write_xlsx

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first.")
        raise SystemExit(1)

    z = ZONES[zone]
    classified = _load_scan_results(results_path)
    audit_ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    zone_name_hyphen = z["name"].replace(" / ", "-").replace(" ", "-")
    query_text = overpass_query(z["bbox"])
    out_dir = _output_dir(zone)

    xlsx_path = out_dir / "reports" / f"OSM-Audit-{zone_name_hyphen}.xlsx"
    write_xlsx(classified, zone, xlsx_path, query_text, audit_ts, output_root=PROJECT_ROOT)

    dash_path = out_dir / "reports" / f"OSM-Audit-{zone_name_hyphen}-Dashboard.html"
    write_dashboard(classified, zone, z["name"], dash_path, audit_ts)

    write_csvs(classified, out_dir / "csv")
    click.echo(f"Reports regenerated in {out_dir}")


# --- notes ---

@main.command()
@click.option(
    "--zone",
    type=click.Choice(ZONE_KEYS),
    default=DEFAULT_ZONE,
    help="Zone to query for OSM notes",
)
@click.option(
    "--force-refresh",
    is_flag=True,
    help="Bypass the 1-hour cache and re-fetch live",
)
@click.option(
    "--status",
    type=click.Choice(["open", "all"]),
    default="open",
    help="Note status filter",
)
def notes(zone: str, force_refresh: bool, status: str):
    """Print community-reported OSM notes for a zone."""
    from .notes import fetch_notes_for_zone

    items = fetch_notes_for_zone(
        zone, force_refresh=force_refresh, status=status
    )
    z = ZONES[zone]
    click.echo(f"OSM Notes — {z['name']} ({status}): {len(items)} note(s)")
    for n in items[:10]:
        comments = n.get("comments") or []
        first_text = (comments[0].get("text") if comments else "") or ""
        first_text_short = (first_text[:80] + "…") if len(first_text) > 80 else first_text
        click.echo(
            f"  #{n['id']}  ({n['lat']:.5f}, {n['lon']:.5f})  "
            f"{n.get('status'):>6}  "
            f"{(n.get('date_created') or '')[:10]}  "
            f"{len(comments)}c  {first_text_short}"
        )
    if len(items) > 10:
        click.echo(f"  …and {len(items) - 10:,} more.")


# --- osmose ---

@main.command()
@click.option(
    "--zone",
    type=click.Choice(ZONE_KEYS),
    default=DEFAULT_ZONE,
    help="Zone to query for Osmose issues",
)
@click.option(
    "--force-refresh",
    is_flag=True,
    help="Bypass the 24-hour cache and re-fetch live",
)
@click.option(
    "--item",
    multiple=True,
    help="Restrict to one or more Osmose item codes (e.g. --item 3070)",
)
def osmose(zone: str, force_refresh: bool, item: tuple[str, ...]):
    """Print Osmose-QA issues for a zone."""
    from .osmose import fetch_issues_for_zone

    item_filter = list(item) if item else None
    items = fetch_issues_for_zone(
        zone,
        force_refresh=force_refresh,
        item_filter=item_filter,
    )
    z = ZONES[zone]
    click.echo(f"Osmose — {z['name']}: {len(items)} issue(s)")
    for i in items[:10]:
        ids = i.get("osm_ids") or {}
        ways = ids.get("ways") or []
        nodes = ids.get("nodes") or []
        relations = ids.get("relations") or []
        first_target = (
            f"way/{ways[0]}" if ways else
            f"node/{nodes[0]}" if nodes else
            f"relation/{relations[0]}" if relations else
            "?"
        )
        click.echo(
            f"  item={i.get('item') or '?':>5}  "
            f"{first_target:<14}  "
            f"{(i.get('item_title') or '')[:50]}  "
            f"{i.get('subtitle') or ''}"
        )
    if len(items) > 10:
        click.echo(f"  …and {len(items) - 10:,} more.")


# --- helpers ---

def _save_scan_results(classified: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "all_ways": classified["all_ways"],
        "class_a": classified["class_a"],
        "class_a_only": classified["class_a_only"],
        "class_ab": classified["class_ab"],
        "class_b_streets": {k: v for k, v in classified["class_b_streets"].items()},
        "gaps": classified["gaps"],
        "summary_stats": classified["summary_stats"],
        "extra_findings": classified.get("extra_findings", []),
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(serializable, fh, ensure_ascii=False)


def _load_scan_results(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
