"""Pre-flight check runner for first-changeset readiness.

Codifies the first 30-ish items of ``docs/community-prep/04-pre-flight-checklist.md``
into executable checks. The remaining items — community publication,
manual fix curation, OSMCha monitoring — require human attestation
and are surfaced as ``MANUAL`` items so the maintainer doesn't lose
track of them.

The intent is *not* to make pre-flight a fully automated gate; it's
to remove the cognitive friction of remembering which items are
codable and to give the maintainer an unambiguous "everything
auto-checkable is green" signal before the human gating pass.

CLI:

    osm preflight --zone blue-ash-montgomery [--strict]

Exit codes:
    0  All FAIL/WARN slots clean (MANUAL items still pending acceptance)
    1  At least one FAIL — stop and fix
    2  At least one WARN with --strict; exit 0 without --strict
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    PROJECT_ROOT,
    TOKEN_PATH,
    WIKI_URL,
)
from .zones import ZONES

# ---------------------------------------------------------------------------
# Check status taxonomy
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
MANUAL = "MANUAL"

# Categories — mirrored into the markdown checklist headings so the
# CLI output and the doc stay structurally aligned.
CAT_COMMUNITY = "Community gating"
CAT_ACCOUNT = "Account hygiene"
CAT_PIPELINE = "Pipeline state"
CAT_SCAN = "Scan freshness"
CAT_FIX = "Fix-batch readiness"
CAT_MONITORING = "Monitoring + post-submission"


@dataclass
class Check:
    """One pre-flight check result."""

    name: str
    category: str
    status: str  # PASS | FAIL | WARN | MANUAL
    detail: str = ""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _output_dir(zone_key: str) -> Path:
    return PROJECT_ROOT / f"osm-audit-{zone_key}"


def _scan_results_path(zone_key: str) -> Path:
    return _output_dir(zone_key) / "scan-results.json"


def _zone_polygon_path(zone_key: str) -> Path:
    return PROJECT_ROOT / "src" / "osm" / "zones" / f"{zone_key}.geojson"


def _newest_baseline_manifest(zone_key: str) -> Path | None:
    data_dir = _output_dir(zone_key) / "data"
    if not data_dir.exists():
        return None
    manifests = sorted(
        data_dir.glob("cagis_baseline_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return manifests[-1] if manifests else None


def _file_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    return time.time() - path.stat().st_mtime


# ---------------------------------------------------------------------------
# Individual checks — each returns a Check
# ---------------------------------------------------------------------------

def check_wiki_url_set() -> Check:
    """The default WIKI_URL is the placeholder; flag if not customised."""
    if WIKI_URL.endswith("Hamilton_County_TIGER_Audit"):
        # The default still points at a placeholder page name. The
        # maintainer should confirm they actually published a page at
        # that URL OR update the constant to match the real page.
        return Check(
            name="config.WIKI_URL points at a published wiki page",
            category=CAT_COMMUNITY,
            status=MANUAL,
            detail=(
                f"WIKI_URL = {WIKI_URL!r}. Confirm a wiki page is published "
                "at exactly that URL, OR update src/osm/config.py:WIKI_URL "
                "to match the real page before submitting."
            ),
        )
    return Check(
        name="config.WIKI_URL set to a non-default value",
        category=CAT_COMMUNITY,
        status=PASS,
        detail=f"WIKI_URL = {WIKI_URL!r}",
    )


def check_community_drafts_present() -> Check:
    """The four community-prep drafts must exist in the repo."""
    base = PROJECT_ROOT / "docs" / "community-prep"
    expected = [
        "01-wiki-page.md",
        "02-talk-us-post.md",
        "03-minh-outreach.md",
        "04-pre-flight-checklist.md",
    ]
    missing = [name for name in expected if not (base / name).exists()]
    if missing:
        return Check(
            name="Community-prep drafts present in repo",
            category=CAT_COMMUNITY,
            status=FAIL,
            detail=f"Missing: {missing}",
        )
    return Check(
        name="Community-prep drafts present in repo",
        category=CAT_COMMUNITY,
        status=PASS,
    )


def check_community_publication_attested() -> Check:
    """Manual: the maintainer must confirm wiki + talk-us + Minh outreach went out."""
    return Check(
        name="Wiki page published, talk-us@ posted ≥14 days ago, "
             "Minh contacted, all replies addressed",
        category=CAT_COMMUNITY,
        status=MANUAL,
        detail=(
            "Confirm by hand. There is no codable path for this — the "
            "community gating pass is the load-bearing trust action."
        ),
    )


def check_oauth_token_present() -> Check:
    if not TOKEN_PATH.exists():
        return Check(
            name="OAuth token saved at ~/.config/osm/token.json",
            category=CAT_ACCOUNT,
            status=FAIL,
            detail=(
                f"{TOKEN_PATH} not found. Run 'osm auth login' to "
                "authenticate against the OSM API."
            ),
        )
    age_days = (_file_age_seconds(TOKEN_PATH) or 0) / 86_400
    if age_days > 7:
        return Check(
            name="OAuth token saved at ~/.config/osm/token.json",
            category=CAT_ACCOUNT,
            status=WARN,
            detail=(
                f"Token last updated {age_days:.1f} days ago. "
                "Re-run 'osm auth login' if production submission is imminent."
            ),
        )
    return Check(
        name="OAuth token saved at ~/.config/osm/token.json",
        category=CAT_ACCOUNT,
        status=PASS,
        detail=f"Token age: {age_days:.1f} days",
    )


def check_oauth_scope_includes_write_api() -> Check:
    """The token must carry write_api for production fix submission."""
    if not TOKEN_PATH.exists():
        return Check(
            name="OAuth token scope includes 'write_api'",
            category=CAT_ACCOUNT,
            status=FAIL,
            detail="No token file to inspect.",
        )
    try:
        with TOKEN_PATH.open("r", encoding="utf-8") as fh:
            tok = json.load(fh)
        scope = (tok.get("scope") or "").lower()
        if "write_api" in scope:
            return Check(
                name="OAuth token scope includes 'write_api'",
                category=CAT_ACCOUNT,
                status=PASS,
                detail=f"scope = {scope!r}",
            )
        return Check(
            name="OAuth token scope includes 'write_api'",
            category=CAT_ACCOUNT,
            status=FAIL,
            detail=(
                f"scope = {scope!r} — re-authenticate with the right scope "
                "via 'osm auth login'."
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return Check(
            name="OAuth token scope includes 'write_api'",
            category=CAT_ACCOUNT,
            status=FAIL,
            detail=f"Token file unreadable: {exc}",
        )


def check_account_naming_convention() -> Check:
    """Manual: the maintainer's import account follows the _cincyimport convention."""
    return Check(
        name="Import account follows the _cincyimport convention",
        category=CAT_ACCOUNT,
        status=MANUAL,
        detail=(
            "OSM account name should end with '_cincyimport' per the "
            "Hamilton County Building Import precedent. Profile bio "
            "should link to the wiki page."
        ),
    )


def check_zone_polygon_present(zone_key: str) -> Check:
    p = _zone_polygon_path(zone_key)
    if not p.exists():
        return Check(
            name=f"Zone polygon present at src/osm/zones/{zone_key}.geojson",
            category=CAT_PIPELINE,
            status=FAIL,
            detail=f"{p} not found.",
        )
    age_days = (_file_age_seconds(p) or 0) / 86_400
    if age_days > 90:
        return Check(
            name=f"Zone polygon present at src/osm/zones/{zone_key}.geojson",
            category=CAT_PIPELINE,
            status=WARN,
            detail=(
                f"Polygon last updated {age_days:.0f} days ago. SORTA may "
                "have shifted the published service map; consider regenerating."
            ),
        )
    return Check(
        name=f"Zone polygon present at src/osm/zones/{zone_key}.geojson",
        category=CAT_PIPELINE,
        status=PASS,
        detail=f"Polygon age: {age_days:.0f} days",
    )


def check_pytest_passes(timeout: int = 60) -> Check:
    try:
        result = subprocess.run(
            ["pytest", "tests/", "-q", "--tb=line"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            lines = (result.stdout or "").strip().splitlines()
            tail = lines[-1] if lines else ""
            return Check(
                name="pytest tests/ passes cleanly",
                category=CAT_PIPELINE,
                status=PASS,
                detail=tail,
            )
        return Check(
            name="pytest tests/ passes cleanly",
            category=CAT_PIPELINE,
            status=FAIL,
            detail=(result.stdout or result.stderr).strip()[-500:],
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return Check(
            name="pytest tests/ passes cleanly",
            category=CAT_PIPELINE,
            status=WARN,
            detail=f"Could not run pytest: {exc}",
        )


def check_ruff_clean(timeout: int = 30) -> Check:
    try:
        result = subprocess.run(
            ["ruff", "check", "src/"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            return Check(
                name="ruff check src/ clean",
                category=CAT_PIPELINE,
                status=PASS,
            )
        return Check(
            name="ruff check src/ clean",
            category=CAT_PIPELINE,
            status=FAIL,
            detail=result.stdout.strip()[-300:],
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return Check(
            name="ruff check src/ clean",
            category=CAT_PIPELINE,
            status=WARN,
            detail=f"Could not run ruff: {exc}",
        )


def check_scan_freshness(zone_key: str) -> Check:
    p = _scan_results_path(zone_key)
    if not p.exists():
        return Check(
            name=f"Recent scan-results.json for {zone_key}",
            category=CAT_SCAN,
            status=FAIL,
            detail=f"{p} not found. Run 'osm scan --zone {zone_key}' first.",
        )
    age_days = (_file_age_seconds(p) or 0) / 86_400
    if age_days > 7:
        return Check(
            name=f"Recent scan-results.json for {zone_key}",
            category=CAT_SCAN,
            status=WARN,
            detail=(
                f"Scan last run {age_days:.1f} days ago; rerun "
                f"'osm scan --zone {zone_key}' for fresh data."
            ),
        )
    return Check(
        name=f"Recent scan-results.json for {zone_key}",
        category=CAT_SCAN,
        status=PASS,
        detail=f"Scan age: {age_days:.1f} days",
    )


def check_baseline_manifest_after_scan(zone_key: str) -> Check:
    """The newest baseline manifest must be at least as new as the scan."""
    scan = _scan_results_path(zone_key)
    manifest = _newest_baseline_manifest(zone_key)
    if not scan.exists():
        return Check(
            name="CAGIS baseline manifest is at least as recent as the scan",
            category=CAT_SCAN,
            status=FAIL,
            detail="No scan-results.json to compare against.",
        )
    if manifest is None:
        return Check(
            name="CAGIS baseline manifest is at least as recent as the scan",
            category=CAT_SCAN,
            status=WARN,
            detail=(
                f"No cagis_baseline_*.json under osm-audit-{zone_key}/data/. "
                f"Run 'osm conflate --zone {zone_key} --baseline-manifest'."
            ),
        )
    if manifest.stat().st_mtime < scan.stat().st_mtime:
        scan_age = (_file_age_seconds(scan) or 0) / 86_400
        manifest_age = (_file_age_seconds(manifest) or 0) / 86_400
        return Check(
            name="CAGIS baseline manifest is at least as recent as the scan",
            category=CAT_SCAN,
            status=WARN,
            detail=(
                f"Manifest is {manifest_age:.1f} days old vs scan "
                f"{scan_age:.1f} days; rerun "
                f"'osm conflate --zone {zone_key} --baseline-manifest'."
            ),
        )
    return Check(
        name="CAGIS baseline manifest is at least as recent as the scan",
        category=CAT_SCAN,
        status=PASS,
        detail=f"Manifest: {manifest.name}",
    )


def check_auto_submit_pool_size(zone_key: str) -> Check:
    """The summary stats should report a non-zero MATCHED_HIGH count."""
    p = _scan_results_path(zone_key)
    if not p.exists():
        return Check(
            name="Auto-submit pool has fixes available",
            category=CAT_FIX,
            status=FAIL,
            detail="No scan-results.json.",
        )
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return Check(
            name="Auto-submit pool has fixes available",
            category=CAT_FIX,
            status=FAIL,
            detail=f"scan-results.json unreadable: {exc}",
        )
    matched = (
        data.get("summary_stats", {}).get("cagis_matched")
        or 0
    )
    if matched == 0:
        return Check(
            name="Auto-submit pool has fixes available",
            category=CAT_FIX,
            status=WARN,
            detail=(
                "summary_stats.cagis_matched = 0 — has 'osm conflate' "
                "been run since the scan? No fixes will be submitted."
            ),
        )
    return Check(
        name="Auto-submit pool has fixes available",
        category=CAT_FIX,
        status=PASS,
        detail=f"cagis_matched = {matched:,}",
    )


def check_first_batch_curated() -> Check:
    """Manual: the maintainer must hand-pick the 10 fixes for the first batch."""
    return Check(
        name="First-batch fixes hand-curated (10 elements, no recent edits, "
             "no community-flagged corridors)",
        category=CAT_FIX,
        status=MANUAL,
        detail=(
            "Pick from the cleanest set_maxspeed_cagis candidates in Blue Ash. "
            "Verify each via osm.org/way/<id>/history; skip any edited in "
            "the last 30 days or flagged on talk-us@."
        ),
    )


def check_dry_run_was_inspected() -> Check:
    """Manual: a human must have looked at the osmChange diff."""
    return Check(
        name="'osm fix --dry-run' executed and the diff was inspected by a human",
        category=CAT_FIX,
        status=MANUAL,
        detail=(
            "Ideally a second reviewer beyond the maintainer. Confirm the "
            "diff has the full tag set: comment, created_by, source, "
            "mechanical=yes, bot=yes, description=<wiki-url>, cagis:attribution."
        ),
    )


def check_route_impact_was_run(zone_key: str) -> Check:
    """The summary should include a route_impact section if oneway fixes are present."""
    p = _scan_results_path(zone_key)
    if not p.exists():
        return Check(
            name="Route-impact harness has been run for the batch",
            category=CAT_FIX,
            status=WARN,
            detail="No scan-results.json.",
        )
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return Check(
            name="Route-impact harness has been run for the batch",
            category=CAT_FIX,
            status=WARN,
            detail="scan-results.json unreadable.",
        )
    impact = (data.get("summary_stats") or {}).get("route_impact")
    if not impact:
        return Check(
            name="Route-impact harness has been run for the batch",
            category=CAT_FIX,
            status=WARN,
            detail=(
                "summary_stats.route_impact missing. Run "
                f"'osm fix-impact --zone {zone_key}' or the inline "
                "'--with-route-impact' flag on dry-run."
            ),
        )
    return Check(
        name="Route-impact harness has been run for the batch",
        category=CAT_FIX,
        status=PASS,
        detail=(
            f"real={impact.get('real', 0)}, "
            f"noisy={impact.get('noisy', 0)}, "
            f"skipped={impact.get('fixes_skipped', 0)}"
        ),
    )


def check_osmcha_subscription() -> Check:
    return Check(
        name="OSMCha subscription configured for the import account",
        category=CAT_MONITORING,
        status=MANUAL,
        detail=(
            "Set up at osmcha.org with notifications via a channel the "
            "maintainer will check within 4 hours of submission."
        ),
    )


def check_post_submission_window_planned() -> Check:
    return Check(
        name="Maintainer has ≥4 hours of clear time after submission to monitor",
        category=CAT_MONITORING,
        status=MANUAL,
        detail="No deploys before bedtime / before a meeting / on Fridays.",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class PreflightReport:
    zone_key: str
    checks: list[Check] = field(default_factory=list)

    @property
    def n_pass(self) -> int:
        return sum(1 for c in self.checks if c.status == PASS)

    @property
    def n_fail(self) -> int:
        return sum(1 for c in self.checks if c.status == FAIL)

    @property
    def n_warn(self) -> int:
        return sum(1 for c in self.checks if c.status == WARN)

    @property
    def n_manual(self) -> int:
        return sum(1 for c in self.checks if c.status == MANUAL)

    def exit_code(self, *, strict: bool = False) -> int:
        if self.n_fail:
            return 1
        if strict and self.n_warn:
            return 2
        return 0


def run_preflight(zone_key: str, *, run_pytest: bool = True) -> PreflightReport:
    """Execute every check and return a structured report.

    ``run_pytest`` exists so test runs can skip the recursive pytest
    invocation (which would otherwise loop forever).
    """
    if zone_key not in ZONES:
        raise KeyError(f"Unknown zone {zone_key!r}; choices: {list(ZONES)}")

    checks: list[Check] = [
        # Community gating
        check_community_drafts_present(),
        check_wiki_url_set(),
        check_community_publication_attested(),
        # Account hygiene
        check_oauth_token_present(),
        check_oauth_scope_includes_write_api(),
        check_account_naming_convention(),
        # Pipeline state
        check_zone_polygon_present(zone_key),
        check_ruff_clean(),
    ]
    if run_pytest:
        checks.append(check_pytest_passes())
    checks.extend([
        # Scan freshness
        check_scan_freshness(zone_key),
        check_baseline_manifest_after_scan(zone_key),
        # Fix-batch readiness
        check_auto_submit_pool_size(zone_key),
        check_route_impact_was_run(zone_key),
        check_first_batch_curated(),
        check_dry_run_was_inspected(),
        # Monitoring
        check_osmcha_subscription(),
        check_post_submission_window_planned(),
    ])

    return PreflightReport(zone_key=zone_key, checks=checks)
