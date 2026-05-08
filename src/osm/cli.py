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
def scan(zone: str, from_cache: bool, skip_history: bool, import_only: bool, with_conflation: bool):
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
        classified = classify(raw)

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
        if with_conflation:
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
                click.echo(f"  Conflation failed: {exc}")

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
