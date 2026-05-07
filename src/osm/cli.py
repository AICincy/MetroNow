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
def scan(zone: str, from_cache: bool, skip_history: bool):
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
        click.echo("\nPhase 1: Fetching Overpass data...")
        raw = fetch_overpass(zk, out_dir)

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

        # Phase 3: Reports
        click.echo("\nPhase 3: Generating reports...")
        zone_name_hyphen = z["name"].replace(" / ", "-").replace(" ", "-")

        from .fetch import overpass_query
        query_text = overpass_query(z["bbox"])

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
def fix(zone: str, dry_run: bool):
    """Review and submit corrections to OSM."""
    from .changeset import submit_fixes
    from .review import review_defects

    results_path = _output_dir(zone) / "scan-results.json"
    if not results_path.exists():
        click.echo(f"No scan results found for {zone}. Run 'osm scan --zone {zone}' first.")
        raise SystemExit(1)

    classified = _load_scan_results(results_path)
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
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(serializable, fh, ensure_ascii=False)


def _load_scan_results(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
