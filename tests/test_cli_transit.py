"""Tests for the transit-* CLI subcommands.

transit-status / transit-budget are presentation over osm.transit.status()
and a calendar-arithmetic budget calculator; transit-networks /
transit-alerts wrap the network-discovery and service-alert helpers.
These tests use the Click test runner with tmp_path-isolated
KEY_FILE / USAGE_FILE / CACHE_DIR so the maintainer's real
~/.config/osm files are never read or written.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from click.testing import CliRunner


@pytest.fixture
def isolated_transit(tmp_path, monkeypatch):
    from osm import transit as t

    monkeypatch.setattr(t, "KEY_FILE", tmp_path / "transit_api.json")
    monkeypatch.setattr(t, "USAGE_FILE", tmp_path / "transit_api_usage.json")
    monkeypatch.setattr(t, "CACHE_DIR", tmp_path / "transit_cache")
    monkeypatch.setattr(t, "_recent_calls", [])
    return t


def _write_usage(t, count: int) -> None:
    t.USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    t.USAGE_FILE.write_text(json.dumps({
        "month": t._current_month_key(),
        "count": count,
    }))


# ---------------------------------------------------------------------------
# transit-status
# ---------------------------------------------------------------------------

class TestTransitStatusCmd:

    def test_no_key_reports_NO(self, isolated_transit):
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-status"])
        assert result.exit_code == 0
        assert "NO" in result.output
        assert "Powered by Transit" in result.output
        assert "5,000" in result.output

    def test_key_present_reports_yes(self, isolated_transit):
        isolated_transit.KEY_FILE.write_text(json.dumps({"api_key": "x"}))
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-status"])
        assert result.exit_code == 0
        assert "Has API key:     yes" in result.output

    def test_quota_used_reflected(self, isolated_transit):
        _write_usage(isolated_transit, 100)
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-status"])
        assert result.exit_code == 0
        assert "Used this month: 100" in result.output


# ---------------------------------------------------------------------------
# transit-budget
# ---------------------------------------------------------------------------

class TestTransitBudgetCmd:

    def test_default_prints_per_day_cap(self, isolated_transit):
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget"])
        assert result.exit_code == 0
        assert "Remaining:" in result.output
        assert "Per-day cap:" in result.output

    def test_calls_within_budget_passes(self, isolated_transit):
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "10"])
        assert result.exit_code == 0
        assert "Fits" in result.output

    def test_calls_exceeding_budget_exits_1(self, isolated_transit):
        # Budget is 5,000 * 0.80 = 4,000 by default.
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "9000"])
        assert result.exit_code == 1
        assert "DOES NOT FIT" in result.output

    def test_calls_negative_exits_2(self, isolated_transit):
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "-1"])
        assert result.exit_code == 2

    def test_budget_with_used_quota(self, isolated_transit):
        # 3900 used, budget is 4000 → only 100 remaining
        _write_usage(isolated_transit, 3900)
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "150"])
        assert result.exit_code == 1
        assert "Short by 50" in result.output


# ---------------------------------------------------------------------------
# transit-networks
# ---------------------------------------------------------------------------

class TestTransitNetworksCmd:

    def test_no_key_exits_1(self, isolated_transit):
        from osm.cli import main
        result = CliRunner().invoke(main, ["transit-networks"])
        assert result.exit_code == 1
        assert "No Transit API key" in result.output

    def test_lists_networks_and_marks_sorta(self, isolated_transit):
        isolated_transit.KEY_FILE.write_text(json.dumps({"api_key": "x"}))
        from osm import transit
        from osm.cli import main
        payload = {"networks": [
            {"global_network_id": "MSP", "network_name": "Metro Transit"},
            {"global_network_id": "SORTA",
             "network_name": "Metro (Southwest Ohio Regional Transit Authority)"},
        ]}
        with mock.patch.object(transit, "available_networks", autospec=True,
                               return_value=payload):
            result = CliRunner().invoke(main, ["transit-networks"])
        assert result.exit_code == 0
        assert "Transit networks: 2" in result.output
        assert "MSP" in result.output and "SORTA" in result.output
        assert "matched as SORTA" in result.output
        assert "Auto-resolved SORTA network id: SORTA" in result.output

    def test_empty_payload_exits_1(self, isolated_transit):
        isolated_transit.KEY_FILE.write_text(json.dumps({"api_key": "x"}))
        from osm import transit
        from osm.cli import main
        with mock.patch.object(transit, "available_networks", autospec=True,
                               return_value=None):
            result = CliRunner().invoke(main, ["transit-networks"])
        assert result.exit_code == 1
        assert "returned nothing" in result.output


# ---------------------------------------------------------------------------
# transit-alerts
# ---------------------------------------------------------------------------

class TestTransitAlertsCmd:

    def test_no_key_is_noop_exit_0(self, isolated_transit):
        from osm.cli import main
        result = CliRunner().invoke(main, ["transit-alerts"])
        assert result.exit_code == 0
        assert "not configured" in result.output

    def test_prints_alerts(self, isolated_transit):
        isolated_transit.KEY_FILE.write_text(json.dumps({"api_key": "x"}))
        from osm import transit
        from osm.cli import main
        with mock.patch.object(
            transit, "fetch_sorta_alerts", autospec=True,
            return_value=[{
                "id": "a", "title": "Detour on Rt 4", "severity": "WARNING",
                "description": "Closed for repaving", "effect": None,
                "url": "https://x",
            }],
        ):
            result = CliRunner().invoke(main, ["transit-alerts"])
        assert result.exit_code == 0
        assert "1 service alert" in result.output
        assert "Detour on Rt 4" in result.output
        assert "WARNING" in result.output
        assert "https://x" in result.output

    def test_no_alerts_message(self, isolated_transit):
        isolated_transit.KEY_FILE.write_text(json.dumps({"api_key": "x"}))
        from osm import transit
        from osm.cli import main
        with mock.patch.object(transit, "fetch_sorta_alerts", autospec=True,
                               return_value=[]):
            result = CliRunner().invoke(main, ["transit-alerts"])
        assert result.exit_code == 0
        assert "No service alerts" in result.output

    def test_network_flag_passed_through(self, isolated_transit):
        isolated_transit.KEY_FILE.write_text(json.dumps({"api_key": "x"}))
        from osm import transit
        from osm.cli import main
        with mock.patch.object(transit, "fetch_sorta_alerts", autospec=True,
                               return_value=[]) as m:
            CliRunner().invoke(main, ["transit-alerts", "--network", "SORTA-X"])
        m.assert_called_once_with(network_id="SORTA-X")


# ---------------------------------------------------------------------------
# _increment_usage concurrency safety (review feedback)
# ---------------------------------------------------------------------------

class TestIncrementUsageLocking:

    def test_serial_increments_match_call_count(self, isolated_transit):
        for _ in range(10):
            isolated_transit._increment_usage()
        assert isolated_transit._read_usage()["count"] == 10

    def test_concurrent_increments_dont_lose_updates(self, isolated_transit):
        """Spawn N threads each incrementing K times; total must equal N*K."""
        import threading

        N_THREADS = 8
        K_PER_THREAD = 25
        barrier = threading.Barrier(N_THREADS)

        def worker():
            # Bounded barrier wait — if any worker crashes before reaching
            # the barrier, the survivors get BrokenBarrierError instead of
            # hanging the test runner indefinitely.
            barrier.wait(timeout=5)
            for _ in range(K_PER_THREAD):
                isolated_transit._increment_usage()

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for tr in threads:
            tr.start()
        for tr in threads:
            tr.join()

        # Without the flock, this assertion fails reliably under contention.
        # With the flock, every increment is preserved.
        assert isolated_transit._read_usage()["count"] == N_THREADS * K_PER_THREAD
