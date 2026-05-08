"""Tests for osm.transit — Transit App API client (skeleton, no live API)."""

from __future__ import annotations

import json
import time
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixture: an isolated tmp_path-backed config dir for every test, so the
# tests never touch the maintainer's real ~/.config/osm/transit_api.json
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_transit(tmp_path, monkeypatch):
    """Redirect KEY_FILE / USAGE_FILE / CACHE_DIR to a tmp_path subtree.

    Also resets the in-process rate-limit counter so tests never sleep.
    """
    from osm import transit as t

    monkeypatch.setattr(t, "KEY_FILE", tmp_path / "transit_api.json")
    monkeypatch.setattr(t, "USAGE_FILE", tmp_path / "transit_api_usage.json")
    monkeypatch.setattr(t, "CACHE_DIR", tmp_path / "transit_cache")
    monkeypatch.setattr(t, "_recent_calls", [])
    return t


def _write_key(t, value: str = "test_key_123") -> None:
    t.KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    t.KEY_FILE.write_text(json.dumps({"api_key": value}))


# ---------------------------------------------------------------------------
# Auth / key loading
# ---------------------------------------------------------------------------

class TestKeyLoading:

    def test_no_key_file_returns_none(self, isolated_transit):
        t = isolated_transit
        assert t._load_api_key() is None

    def test_missing_api_key_field_returns_none(self, isolated_transit):
        t = isolated_transit
        t.KEY_FILE.write_text(json.dumps({"other_field": "x"}))
        assert t._load_api_key() is None

    def test_valid_key_file_returns_value(self, isolated_transit):
        t = isolated_transit
        _write_key(t, "abc123")
        assert t._load_api_key() == "abc123"

    def test_malformed_json_returns_none(self, isolated_transit):
        t = isolated_transit
        t.KEY_FILE.write_text("not json {{")
        assert t._load_api_key() is None


# ---------------------------------------------------------------------------
# Quota counter
# ---------------------------------------------------------------------------

class TestQuotaCounter:

    def test_fresh_state_has_zero_count(self, isolated_transit):
        t = isolated_transit
        s = t.status()
        assert s.used_this_month == 0
        assert s.quota_exhausted is False
        assert s.budget_cap == int(
            t.MONTHLY_QUOTA_FREE_TIER * t.QUOTA_BUDGET_FRACTION
        )

    def test_increment_persists(self, isolated_transit):
        t = isolated_transit
        t._increment_usage()
        t._increment_usage()
        assert t._read_usage()["count"] == 2

    def test_quota_exhausted_at_budget_cap(self, isolated_transit):
        t = isolated_transit
        t._write_usage({"month": t._current_month_key(), "count": t._budget_cap()})
        assert t._quota_exhausted() is True

    def test_month_rollover_resets_counter(self, isolated_transit):
        t = isolated_transit
        # Pretend it's still last month with counter at the cap
        t._write_usage({"month": "2020-01", "count": 9_999})
        # _read_usage detects the rollover
        usage = t._read_usage()
        assert usage["month"] == t._current_month_key()
        assert usage["count"] == 0


# ---------------------------------------------------------------------------
# Rate limiting (no real sleeps)
# ---------------------------------------------------------------------------

class TestRateLimit:

    def test_first_call_does_not_sleep(self, isolated_transit, monkeypatch):
        t = isolated_transit
        slept = []
        monkeypatch.setattr(t.time, "sleep", lambda s: slept.append(s))
        t._rate_limit_pace()
        assert slept == []

    def test_sixth_call_sleeps_for_window(self, isolated_transit, monkeypatch):
        t = isolated_transit
        slept = []
        monkeypatch.setattr(t.time, "sleep", lambda s: slept.append(s))
        # Pretend 5 calls all happened "now"
        now = time.monotonic()
        t._recent_calls.extend([now] * t.RATE_LIMIT_PER_MINUTE)
        t._rate_limit_pace()
        assert slept and 0 < slept[0] <= 60.5


# ---------------------------------------------------------------------------
# _request — fail-open behaviours
# ---------------------------------------------------------------------------

class TestRequestFailOpen:

    def test_no_key_returns_none_without_calling_network(
        self, isolated_transit,
    ):
        t = isolated_transit
        with mock.patch.object(t.requests, "get", autospec=True) as mreq:
            out = t._request("nearby_stops", {"lat": 39, "lon": -84})
            assert out is None
            assert mreq.call_count == 0

    def test_quota_exhausted_returns_none_without_calling_network(
        self, isolated_transit,
    ):
        t = isolated_transit
        _write_key(t)
        t._write_usage({"month": t._current_month_key(), "count": t._budget_cap()})
        with mock.patch.object(t.requests, "get", autospec=True) as mreq:
            out = t._request("nearby_stops", {"lat": 39, "lon": -84})
            assert out is None
            assert mreq.call_count == 0

    def test_429_response_returns_none_and_counts_against_quota(
        self, isolated_transit,
    ):
        t = isolated_transit
        _write_key(t)

        class _R:
            status_code = 429
            def raise_for_status(self): pass
            def json(self): return {}

        with mock.patch.object(
            t.requests, "get", autospec=True, return_value=_R(),
        ):
            out = t._request("nearby_stops", {"lat": 39, "lon": -84})
        assert out is None
        # Even 429 counts against quota — Transit tracks our calls
        assert t._read_usage()["count"] == 1

    def test_network_error_returns_none(self, isolated_transit):
        t = isolated_transit
        _write_key(t)
        with mock.patch.object(
            t.requests, "get", autospec=True,
            side_effect=t.requests.RequestException("offline"),
        ):
            out = t._request("nearby_stops", {"lat": 39, "lon": -84})
        assert out is None


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

class TestCache:

    def test_cache_hit_does_not_call_network(self, isolated_transit):
        t = isolated_transit
        _write_key(t)
        # Pre-populate the cache for a specific request
        t._write_cached(
            "nearby_stops", {"lat": 39, "lon": -84, "max_distance": 500},
            {"stops": [{"id": "x"}]},
        )
        with mock.patch.object(t.requests, "get", autospec=True) as mreq:
            out = t.nearby_stops(39, -84)
            assert out == {"stops": [{"id": "x"}]}
            assert mreq.call_count == 0
        # Cache hit doesn't count against quota
        assert t._read_usage()["count"] == 0

    def test_force_refresh_skips_cache(self, isolated_transit):
        t = isolated_transit
        _write_key(t)
        t._write_cached("available_networks", None, {"old": True})

        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"new": True}

        with mock.patch.object(
            t.requests, "get", autospec=True, return_value=_R(),
        ) as mreq:
            out = t.available_networks(force_refresh=True)
        assert out == {"new": True}
        assert mreq.call_count == 1


# ---------------------------------------------------------------------------
# Endpoint helpers — verify they hit the right path
# ---------------------------------------------------------------------------

class TestEndpointHelpers:

    def _stub_response(self, payload: dict):
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return payload
        return _R()

    def test_available_networks_path(self, isolated_transit):
        t = isolated_transit
        _write_key(t)
        with mock.patch.object(
            t.requests, "get", autospec=True,
            return_value=self._stub_response({"networks": []}),
        ) as mreq:
            t.available_networks(force_refresh=True)
        assert mreq.call_args.args[0].endswith("/v4/public/available_networks")
        # Auth header present
        headers = mreq.call_args.kwargs["headers"]
        assert headers[t.AUTH_HEADER] == "test_key_123"
        assert "MetroNow" in headers["User-Agent"]

    def test_nearby_stops_includes_lat_lon(self, isolated_transit):
        t = isolated_transit
        _write_key(t)
        with mock.patch.object(
            t.requests, "get", autospec=True,
            return_value=self._stub_response({}),
        ) as mreq:
            t.nearby_stops(39.232, -84.378, max_distance=300, force_refresh=True)
        params = mreq.call_args.kwargs["params"]
        assert params["lat"] == 39.232
        assert params["lon"] == -84.378
        assert params["max_distance"] == 300

    def test_alerts_for_networks_joins_ids(self, isolated_transit):
        t = isolated_transit
        _write_key(t)
        with mock.patch.object(
            t.requests, "get", autospec=True,
            return_value=self._stub_response({}),
        ) as mreq:
            t.alerts_for_networks(["abc", "xyz"], force_refresh=True)
        params = mreq.call_args.kwargs["params"]
        assert params["global_network_ids"] == "abc,xyz"


# ---------------------------------------------------------------------------
# Status snapshot
# ---------------------------------------------------------------------------

class TestStatus:

    def test_status_reflects_no_key(self, isolated_transit):
        s = isolated_transit.status()
        assert s.has_key is False
        assert s.used_this_month == 0
        assert s.quota_exhausted is False

    def test_status_reflects_key_present(self, isolated_transit):
        _write_key(isolated_transit)
        assert isolated_transit.status().has_key is True

    def test_status_reflects_quota_exhausted(self, isolated_transit):
        t = isolated_transit
        t._write_usage({"month": t._current_month_key(), "count": t._budget_cap()})
        s = t.status()
        assert s.quota_exhausted is True
        assert s.used_this_month == s.budget_cap


# ---------------------------------------------------------------------------
# ToS / attribution constants — locked down by tests so they can't drift
# ---------------------------------------------------------------------------

class TestComplianceConstants:

    def test_attribution_string_matches_tos(self, isolated_transit):
        # Transit's ToS requires "Powered by Transit" verbatim.
        assert isolated_transit.POWERED_BY_TRANSIT_ATTRIBUTION == "Powered by Transit"

    def test_user_agent_identifies_project(self, isolated_transit):
        assert "MetroNow" in isolated_transit.USER_AGENT
        assert "github.com/AICincy/MetroNow" in isolated_transit.USER_AGENT

    def test_quota_constants_match_free_tier(self, isolated_transit):
        # Locked to Transit's email at issuance (1,500/month + 5/min).
        # If the maintainer raises these, double-check the new tier letter.
        assert isolated_transit.MONTHLY_QUOTA_FREE_TIER == 1_500
        assert isolated_transit.RATE_LIMIT_PER_MINUTE == 5
