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
def scan(
    zone: str, from_cache: bool, skip_history: bool, import_only: bool,
    with_conflation: bool, tiger_only: bool, with_route_diff: bool,
    route_diff_profile: str, include_unnamed_service: bool,
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
        classified = classify(raw, include_unnamed_service=include_unnamed_service)

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
def fix(zone: str, dry_run: bool, annotate_fixes: bool):
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
def conflate(zone: str, force_refresh: bool):
    """Conflate the most recent scan against CAGIS street centerlines.

    Reads ``scan-results.json`` for ``--zone``, loads the CAGIS centerlines
    for that zone (cached locally for 90 days), runs the spatial match,
    and rewrites ``scan-results.json`` with ``cagis_match`` attached to
    every way. The web UI picks the new fields up automatically.

    Source: CAGIS Open Data Hub, Hamilton County, Ohio.
    """
    from .conflate import (
        SHAPELY_AVAILABLE,
        build_index,
        load_cagis_for_zone,
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
