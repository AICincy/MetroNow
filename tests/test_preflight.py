"""Tests for osm.preflight — first-changeset readiness checks.

The preflight module pokes the filesystem and (optionally) shells out to
pytest/ruff. Every test here uses tmp_path-isolated paths so the
maintainer's real ~/.config/osm and the project's real osm-audit-* trees
are never read or mutated. ``run_pytest=False`` is passed everywhere
to keep the recursive pytest invocation from looping forever.
"""

from __future__ import annotations

import json
import time

import pytest

from osm import preflight as pf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect every path the preflight module touches into tmp_path."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    # docs/community-prep, src/osm/zones, osm-audit-*/, etc., all root here
    monkeypatch.setattr(pf, "PROJECT_ROOT", project_root)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    token_path = config_dir / "token.json"
    monkeypatch.setattr(pf, "TOKEN_PATH", token_path)

    monkeypatch.setattr(
        pf, "WIKI_URL",
        "https://wiki.openstreetmap.org/wiki/Hamilton_County_TIGER_Audit",
    )

    return project_root


def _write_zone_polygon(root, zone_key="blue-ash-montgomery"):
    p = root / "src" / "osm" / "zones" / f"{zone_key}.geojson"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "Polygon", "coordinates": [[]]}))
    return p


def _write_drafts(root):
    base = root / "docs" / "community-prep"
    base.mkdir(parents=True, exist_ok=True)
    for name in (
        "01-wiki-page.md",
        "02-talk-us-post.md",
        "03-minh-outreach.md",
        "04-pre-flight-checklist.md",
    ):
        (base / name).write_text(f"# {name}\n")


def _write_token(token_path, scope="read_prefs write_api"):
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps({
        "access_token": "x",
        "token_type": "Bearer",
        "scope": scope,
    }))


def _write_scan(root, zone_key="blue-ash-montgomery", *, cagis_matched=42):
    out_dir = root / f"osm-audit-{zone_key}"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "scan-results.json"
    p.write_text(json.dumps({
        "summary_stats": {
            "cagis_matched": cagis_matched,
            "route_impact": {"real": 1, "noisy": 0, "fixes_skipped": 0},
        }
    }))
    return p


def _write_baseline_manifest(root, zone_key="blue-ash-montgomery", suffix="A"):
    data_dir = root / f"osm-audit-{zone_key}" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / f"cagis_baseline_{suffix}.json"
    p.write_text(json.dumps({"buckets": {}}))
    return p


# ---------------------------------------------------------------------------
# Status taxonomy + dataclass
# ---------------------------------------------------------------------------

class TestReportSummary:

    def test_counts_by_status(self):
        rep = pf.PreflightReport(zone_key="z", checks=[
            pf.Check("a", pf.CAT_PIPELINE, pf.PASS),
            pf.Check("b", pf.CAT_PIPELINE, pf.PASS),
            pf.Check("c", pf.CAT_PIPELINE, pf.FAIL),
            pf.Check("d", pf.CAT_PIPELINE, pf.WARN),
            pf.Check("e", pf.CAT_COMMUNITY, pf.MANUAL),
        ])
        assert rep.n_pass == 2
        assert rep.n_fail == 1
        assert rep.n_warn == 1
        assert rep.n_manual == 1

    def test_exit_code_clean(self):
        rep = pf.PreflightReport(
            zone_key="z",
            checks=[pf.Check("a", pf.CAT_PIPELINE, pf.PASS)],
        )
        assert rep.exit_code() == 0
        assert rep.exit_code(strict=True) == 0

    def test_exit_code_fail_dominates(self):
        rep = pf.PreflightReport(zone_key="z", checks=[
            pf.Check("a", pf.CAT_PIPELINE, pf.WARN),
            pf.Check("b", pf.CAT_PIPELINE, pf.FAIL),
        ])
        assert rep.exit_code() == 1
        assert rep.exit_code(strict=True) == 1

    def test_exit_code_strict_warn(self):
        rep = pf.PreflightReport(
            zone_key="z",
            checks=[pf.Check("a", pf.CAT_PIPELINE, pf.WARN)],
        )
        assert rep.exit_code() == 0
        assert rep.exit_code(strict=True) == 2


# ---------------------------------------------------------------------------
# Community gating
# ---------------------------------------------------------------------------

class TestCommunityChecks:

    def test_drafts_missing_fails(self, isolated):
        c = pf.check_community_drafts_present()
        assert c.status == pf.FAIL
        assert "Missing" in c.detail

    def test_drafts_present_passes(self, isolated):
        _write_drafts(isolated)
        c = pf.check_community_drafts_present()
        assert c.status == pf.PASS

    def test_wiki_url_default_is_manual(self, isolated):
        c = pf.check_wiki_url_set()
        assert c.status == pf.MANUAL

    def test_wiki_url_customised_passes(self, isolated, monkeypatch):
        monkeypatch.setattr(
            pf, "WIKI_URL",
            "https://wiki.openstreetmap.org/wiki/MetroNow_Audit",
        )
        c = pf.check_wiki_url_set()
        assert c.status == pf.PASS

    def test_publication_attestation_is_manual(self):
        c = pf.check_community_publication_attested()
        assert c.status == pf.MANUAL


# ---------------------------------------------------------------------------
# Account hygiene
# ---------------------------------------------------------------------------

class TestAccountChecks:

    def test_no_token_fails(self, isolated):
        c = pf.check_oauth_token_present()
        assert c.status == pf.FAIL
        assert "auth login" in c.detail

    def test_fresh_token_passes(self, isolated):
        _write_token(pf.TOKEN_PATH)
        c = pf.check_oauth_token_present()
        assert c.status == pf.PASS

    def test_stale_token_warns(self, isolated):
        _write_token(pf.TOKEN_PATH)
        # Push mtime back 30 days
        old = time.time() - 30 * 86_400
        import os
        os.utime(pf.TOKEN_PATH, (old, old))
        c = pf.check_oauth_token_present()
        assert c.status == pf.WARN

    def test_scope_check_fails_without_token(self, isolated):
        c = pf.check_oauth_scope_includes_write_api()
        assert c.status == pf.FAIL

    def test_scope_check_passes_when_write_api_present(self, isolated):
        _write_token(pf.TOKEN_PATH, scope="read_prefs write_api")
        c = pf.check_oauth_scope_includes_write_api()
        assert c.status == pf.PASS

    def test_scope_check_fails_when_write_api_missing(self, isolated):
        _write_token(pf.TOKEN_PATH, scope="read_prefs")
        c = pf.check_oauth_scope_includes_write_api()
        assert c.status == pf.FAIL

    def test_account_naming_is_manual(self):
        c = pf.check_account_naming_convention()
        assert c.status == pf.MANUAL


# ---------------------------------------------------------------------------
# Pipeline state — zone polygon
# ---------------------------------------------------------------------------

class TestZonePolygon:

    def test_missing_polygon_fails(self, isolated):
        c = pf.check_zone_polygon_present("blue-ash-montgomery")
        assert c.status == pf.FAIL

    def test_recent_polygon_passes(self, isolated):
        _write_zone_polygon(isolated, "blue-ash-montgomery")
        c = pf.check_zone_polygon_present("blue-ash-montgomery")
        assert c.status == pf.PASS


# ---------------------------------------------------------------------------
# Scan freshness
# ---------------------------------------------------------------------------

class TestScanFreshness:

    def test_no_scan_fails(self, isolated):
        c = pf.check_scan_freshness("blue-ash-montgomery")
        assert c.status == pf.FAIL

    def test_fresh_scan_passes(self, isolated):
        _write_scan(isolated)
        c = pf.check_scan_freshness("blue-ash-montgomery")
        assert c.status == pf.PASS

    def test_stale_scan_warns(self, isolated):
        p = _write_scan(isolated)
        old = time.time() - 14 * 86_400
        import os
        os.utime(p, (old, old))
        c = pf.check_scan_freshness("blue-ash-montgomery")
        assert c.status == pf.WARN


class TestBaselineManifest:

    def test_no_scan_fails(self, isolated):
        c = pf.check_baseline_manifest_after_scan("blue-ash-montgomery")
        assert c.status == pf.FAIL

    def test_no_manifest_warns(self, isolated):
        _write_scan(isolated)
        c = pf.check_baseline_manifest_after_scan("blue-ash-montgomery")
        assert c.status == pf.WARN

    def test_stale_manifest_warns(self, isolated):
        manifest = _write_baseline_manifest(isolated)
        # Manifest first, then a newer scan
        time.sleep(0.01)
        _write_scan(isolated)
        # ensure manifest is older than scan
        old = time.time() - 60
        import os
        os.utime(manifest, (old, old))
        c = pf.check_baseline_manifest_after_scan("blue-ash-montgomery")
        assert c.status == pf.WARN

    def test_manifest_after_scan_passes(self, isolated):
        _write_scan(isolated)
        time.sleep(0.01)
        _write_baseline_manifest(isolated)
        c = pf.check_baseline_manifest_after_scan("blue-ash-montgomery")
        assert c.status == pf.PASS


# ---------------------------------------------------------------------------
# Fix-batch readiness
# ---------------------------------------------------------------------------

class TestAutoSubmitPool:

    def test_no_scan_fails(self, isolated):
        c = pf.check_auto_submit_pool_size("blue-ash-montgomery")
        assert c.status == pf.FAIL

    def test_zero_matched_warns(self, isolated):
        _write_scan(isolated, cagis_matched=0)
        c = pf.check_auto_submit_pool_size("blue-ash-montgomery")
        assert c.status == pf.WARN

    def test_nonzero_matched_passes(self, isolated):
        _write_scan(isolated, cagis_matched=128)
        c = pf.check_auto_submit_pool_size("blue-ash-montgomery")
        assert c.status == pf.PASS
        assert "128" in c.detail


class TestRouteImpact:

    def test_no_scan_warns(self, isolated):
        c = pf.check_route_impact_was_run("blue-ash-montgomery")
        assert c.status == pf.WARN

    def test_route_impact_present_passes(self, isolated):
        _write_scan(isolated)
        c = pf.check_route_impact_was_run("blue-ash-montgomery")
        assert c.status == pf.PASS

    def test_route_impact_missing_warns(self, isolated):
        out_dir = isolated / "osm-audit-blue-ash-montgomery"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "scan-results.json").write_text(
            json.dumps({"summary_stats": {"cagis_matched": 1}}),
        )
        c = pf.check_route_impact_was_run("blue-ash-montgomery")
        assert c.status == pf.WARN


class TestManualCheckpoints:

    def test_first_batch_curated_is_manual(self):
        assert pf.check_first_batch_curated().status == pf.MANUAL

    def test_dry_run_is_manual(self):
        assert pf.check_dry_run_was_inspected().status == pf.MANUAL

    def test_osmcha_is_manual(self):
        assert pf.check_osmcha_subscription().status == pf.MANUAL

    def test_post_submission_window_is_manual(self):
        assert pf.check_post_submission_window_planned().status == pf.MANUAL


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class TestRunPreflight:

    def test_unknown_zone_raises(self, isolated):
        with pytest.raises(KeyError):
            pf.run_preflight("not-a-zone", run_pytest=False)

    def test_full_pass_path(self, isolated, monkeypatch):
        # Wire every codable check to PASS
        _write_drafts(isolated)
        monkeypatch.setattr(
            pf, "WIKI_URL",
            "https://wiki.openstreetmap.org/wiki/MetroNow_Audit",
        )
        _write_token(pf.TOKEN_PATH)
        _write_zone_polygon(isolated, "blue-ash-montgomery")
        _write_scan(isolated)
        time.sleep(0.01)
        _write_baseline_manifest(isolated)

        # Stub ruff to PASS without invoking the binary
        monkeypatch.setattr(
            pf, "check_ruff_clean",
            lambda: pf.Check("ruff check src/ clean", pf.CAT_PIPELINE, pf.PASS),
        )

        rep = pf.run_preflight("blue-ash-montgomery", run_pytest=False)
        assert rep.n_fail == 0
        # The 4-ish MANUAL items + WIKI_URL placeholder + account-naming
        # all stay MANUAL by design.
        assert rep.n_manual >= 4
        assert rep.exit_code() == 0

    def test_skip_pytest_omits_the_check(self, isolated, monkeypatch):
        monkeypatch.setattr(
            pf, "check_ruff_clean",
            lambda: pf.Check("ruff", pf.CAT_PIPELINE, pf.PASS),
        )
        rep = pf.run_preflight("blue-ash-montgomery", run_pytest=False)
        names = [c.name for c in rep.checks]
        assert not any("pytest" in n for n in names)
