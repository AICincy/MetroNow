"""Tests for the transit-status / transit-budget CLI subcommands.

The two commands are pure presentation layer over osm.transit.status()
and a calendar-arithmetic budget calculator. These tests use the Click
test runner with tmp_path-isolated KEY_FILE / USAGE_FILE so the
maintainer's real ~/.config/osm files are never read or written.
"""

from __future__ import annotations

import json

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
        assert "1,500" in result.output

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
        # Budget is 1,500 * 0.80 = 1,200 by default.
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "5000"])
        assert result.exit_code == 1
        assert "DOES NOT FIT" in result.output

    def test_calls_negative_exits_2(self, isolated_transit):
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "-1"])
        assert result.exit_code == 2

    def test_budget_with_used_quota(self, isolated_transit):
        # 1100 used, budget is 1200 → only 100 remaining
        _write_usage(isolated_transit, 1100)
        from osm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["transit-budget", "--calls", "150"])
        assert result.exit_code == 1
        assert "Short by 50" in result.output


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
            barrier.wait()
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
