"""Tests for osm.feed_errors — process-local fail-open counter."""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def reset_counter():
    from osm import feed_errors
    feed_errors.reset()
    yield
    feed_errors.reset()


# ---------------------------------------------------------------------------
# Counter primitives
# ---------------------------------------------------------------------------

class TestCounter:

    def test_empty_state(self):
        from osm import feed_errors
        s = feed_errors.summary()
        assert s["total"] == 0
        assert s["by_feed"] == {}
        assert s["by_pair"] == []

    def test_single_record(self):
        from osm import feed_errors
        feed_errors.record("notes", "timeout", detail="connect timeout")
        s = feed_errors.summary()
        assert s["total"] == 1
        assert s["by_feed"] == {"notes": 1}
        assert s["by_pair"] == [{"feed": "notes", "reason": "timeout", "count": 1}]
        assert len(s["samples"]) == 1
        assert s["samples"][0]["detail"] == "connect timeout"

    def test_multiple_pairs_aggregated(self):
        from osm import feed_errors
        feed_errors.record("notes", "timeout")
        feed_errors.record("notes", "timeout")
        feed_errors.record("notes", "http_error", detail="HTTP 503")
        feed_errors.record("osmose", "timeout")
        s = feed_errors.summary()
        assert s["total"] == 4
        assert s["by_feed"] == {"notes": 3, "osmose": 1}
        # Most-common ordering
        pairs = {(p["feed"], p["reason"]): p["count"] for p in s["by_pair"]}
        assert pairs[("notes", "timeout")] == 2
        assert pairs[("notes", "http_error")] == 1
        assert pairs[("osmose", "timeout")] == 1

    def test_sample_cap_per_pair(self):
        from osm import feed_errors
        for i in range(10):
            feed_errors.record("transit", "rate_limit", detail=f"call {i}")
        s = feed_errors.summary()
        # Counts are uncapped; only the stored samples are capped.
        assert s["total"] == 10
        notes_samples = [x for x in s["samples"] if x["feed"] == "transit"]
        assert len(notes_samples) <= 3

    def test_reset_clears_state(self):
        from osm import feed_errors
        feed_errors.record("notes", "timeout")
        feed_errors.record("osmose", "http_error")
        feed_errors.reset()
        assert feed_errors.summary()["total"] == 0

    def test_format_human_empty(self):
        from osm import feed_errors
        assert feed_errors.format_human() == ""

    def test_format_human_nonempty(self):
        from osm import feed_errors
        feed_errors.record("notes", "timeout")
        feed_errors.record("notes", "timeout")
        feed_errors.record("osmose", "rate_limit")
        out = feed_errors.format_human()
        assert "3" in out  # total
        assert "notes" in out and "timeout" in out
        assert "osmose" in out and "rate_limit" in out


# ---------------------------------------------------------------------------
# Wiring: each feed module records correctly on fail-open
# ---------------------------------------------------------------------------

class TestNotesWiring:

    def test_notes_request_exception_records(self, tmp_path, monkeypatch):
        from osm import feed_errors
        from osm import notes as notes_mod
        import requests
        # Disable cache so the request actually fires
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path / "cache")
        with mock.patch.object(notes_mod.requests, "get", autospec=True,
                               side_effect=requests.RequestException("offline")):
            out = notes_mod.fetch_notes((39.0, -84.5, 39.1, -84.4),
                                        force_refresh=True)
        assert out == []
        s = feed_errors.summary()
        assert s["by_feed"].get("notes") == 1


class TestOsmoseWiring:

    def test_osmose_http_error_records(self, tmp_path, monkeypatch):
        from osm import feed_errors
        from osm import osmose as osmose_mod
        import requests
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path / "cache")

        class _R:
            status_code = 503
            def raise_for_status(self):
                raise requests.HTTPError("503")
            def json(self):
                return {}

        with mock.patch.object(osmose_mod.requests, "get", autospec=True,
                               return_value=_R()):
            out = osmose_mod.fetch_issues((39.0, -84.5, 39.1, -84.4),
                                          force_refresh=True)
        assert out == []
        s = feed_errors.summary()
        assert s["by_feed"].get("osmose") == 1
        assert any(p["reason"] == "http_error"
                   for p in s["by_pair"]
                   if p["feed"] == "osmose")


class TestMotisWiring:

    def test_motis_connection_refused_records(self, tmp_path, monkeypatch):
        from osm import feed_errors
        from osm import motis as motis_mod
        import requests
        monkeypatch.setattr(motis_mod, "MOTIS_CACHE_DIR", tmp_path / "motis_cache")
        monkeypatch.delenv("MOTIS_BASE", raising=False)
        with mock.patch.object(motis_mod.requests, "get", autospec=True,
                               side_effect=requests.RequestException("refused")):
            out = motis_mod.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is None
        s = feed_errors.summary()
        assert s["by_feed"].get("motis") == 1
        assert any(p["reason"] == "network"
                   for p in s["by_pair"]
                   if p["feed"] == "motis")
