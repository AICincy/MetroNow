"""Tests for osm.osmose — Osmose-QA integration."""

from __future__ import annotations

import json
import os
import time
from unittest import mock


# ---------------------------------------------------------------------------
# Sample Osmose payload modelled on the verified live Blue Ash issue
# ---------------------------------------------------------------------------

def _sample_payload() -> dict:
    """Mirrors the real ``/api/0.3/issues?bbox=…&full=true`` response shape.

    Verified live 2026-05-08 against Blue Ash bbox: way 680900580 (Eastwood
    Circle) carrying item 3070 "Multiple values" for
    ``addr:street=Eastwood Circle;Eastwood East Circle``.
    """
    return {
        "issues": [
            {
                "uuid": "abc-1",
                "item": "3070",
                "title": {"auto": "Multiple values", "en": "Multiple values"},
                "subtitle": {"auto": "addr:street has 2 values"},
                "lat": 39.243,
                "lon": -84.382,
                "elems": [{"type": "way", "id": 680900580}],
            },
            {
                "uuid": "abc-2",
                "item": "1040",
                "title": "Highway not connected",
                "subtitle": "highway disconnected",
                "lat": 39.20,
                "lon": -84.40,
                "elems": ["node/12345", "way/22222"],
            },
            # Garbage-in: Osmose drops or returns malformed entries
            # occasionally — make sure we filter them out gracefully.
            {"uuid": None, "item": None},
        ],
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize:

    def test_normalize_first_issue(self):
        from osm.osmose import _normalize_issue
        payload = _sample_payload()
        n = _normalize_issue(payload["issues"][0])
        assert n is not None
        assert n["id"] == "abc-1"
        assert n["item"] == "3070"
        assert n["item_title"] == "Multiple values"
        assert n["lat"] == 39.243
        assert n["lon"] == -84.382
        assert n["osm_ids"]["ways"] == [680900580]
        assert "abc-1" in n["url"]

    def test_normalize_string_elems(self):
        from osm.osmose import _normalize_issue
        n = _normalize_issue(_sample_payload()["issues"][1])
        assert n is not None
        assert 22222 in n["osm_ids"]["ways"]
        assert 12345 in n["osm_ids"]["nodes"]

    def test_normalize_drops_useless(self):
        from osm.osmose import _normalize_issue
        n = _normalize_issue({"uuid": None, "item": None})
        assert n is None

    def test_normalize_handles_legacy_dict_elems(self):
        from osm.osmose import _normalize_issue
        legacy = {
            "uuid": "x",
            "item": "1",
            "elems": {"ways": [42], "nodes": [7], "relations": [99]},
        }
        n = _normalize_issue(legacy)
        assert n is not None
        assert 42 in n["osm_ids"]["ways"]
        assert 7 in n["osm_ids"]["nodes"]
        assert 99 in n["osm_ids"]["relations"]


# ---------------------------------------------------------------------------
# fetch_issues — patched HTTP
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class TestFetchIssues:

    def test_fetch_issues_normalizes_response(self, tmp_path, monkeypatch):
        from osm import osmose as osmose_mod
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path)
        with mock.patch(
            "osm.osmose.requests.get",
            return_value=_MockResponse(_sample_payload()),
        ) as m:
            result = osmose_mod.fetch_issues(
                (39.16, -84.44, 39.24, -84.33), force_refresh=True
            )
        assert m.call_count == 1
        url = m.call_args[0][0]
        assert "full=true" in url
        # Two valid issues, one filtered out as useless.
        assert len(result) == 2
        assert any(i["id"] == "abc-1" for i in result)

    def test_empty_response_is_no_op(self, tmp_path, monkeypatch):
        from osm import osmose as osmose_mod
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path)
        with mock.patch(
            "osm.osmose.requests.get",
            return_value=_MockResponse({"issues": []}),
        ):
            result = osmose_mod.fetch_issues(
                (39.0, -85.0, 39.01, -84.99), force_refresh=True
            )
        assert result == []

    def test_malformed_response_returns_empty(self, tmp_path, monkeypatch):
        from osm import osmose as osmose_mod
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path)
        with mock.patch(
            "osm.osmose.requests.get",
            return_value=_MockResponse({"unexpected": "shape"}),
        ):
            result = osmose_mod.fetch_issues(
                (39.0, -85.0, 39.01, -84.99), force_refresh=True
            )
        assert result == []

    def test_http_error_returns_empty(self, tmp_path, monkeypatch):
        from osm import osmose as osmose_mod
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path)
        import requests
        with mock.patch(
            "osm.osmose.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ):
            result = osmose_mod.fetch_issues(
                (39.0, -85.0, 39.01, -84.99), force_refresh=True
            )
        assert result == []

    def test_cache_ttl_respected(self, tmp_path, monkeypatch):
        from osm import osmose as osmose_mod
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path)
        with mock.patch(
            "osm.osmose.requests.get",
            return_value=_MockResponse(_sample_payload()),
        ) as m:
            osmose_mod.fetch_issues(
                (39.16, -84.44, 39.24, -84.33), force_refresh=True
            )
            osmose_mod.fetch_issues((39.16, -84.44, 39.24, -84.33))
        assert m.call_count == 1

    def test_cache_ttl_expired_refetches(self, tmp_path, monkeypatch):
        from osm import osmose as osmose_mod
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_DIR", tmp_path)
        monkeypatch.setattr(osmose_mod, "OSMOSE_CACHE_TTL_S", 1)
        with mock.patch(
            "osm.osmose.requests.get",
            return_value=_MockResponse(_sample_payload()),
        ) as m:
            osmose_mod.fetch_issues(
                (39.16, -84.44, 39.24, -84.33), force_refresh=True
            )
            for p in tmp_path.glob("*.json"):
                old = time.time() - 5
                os.utime(p, (old, old))
            osmose_mod.fetch_issues((39.16, -84.44, 39.24, -84.33))
        assert m.call_count == 2


# ---------------------------------------------------------------------------
# Indexing + annotation
# ---------------------------------------------------------------------------

class TestAnnotate:

    def test_index_keys_by_type_and_id(self):
        from osm.osmose import index_issues_by_osm_id
        issues = [
            {
                "id": "x",
                "item": "3070",
                "osm_ids": {"ways": [680900580], "nodes": [], "relations": []},
                "url": "https://osmose.openstreetmap.fr/issue/x",
            }
        ]
        idx = index_issues_by_osm_id(issues)
        assert ("way", 680900580) in idx
        assert idx[("way", 680900580)][0]["id"] == "x"

    def test_fix_on_flagged_way_gets_match(self):
        from osm.osmose import annotate_fixes_with_osmose
        fixes = [
            {
                "kind": "remove_false_oneway",
                "action": "remove_tag",
                "tag": "oneway",
                "element_type": "way",
                "element_id": 680900580,
                "requires_human_review": False,
            }
        ]
        issues = [
            {
                "id": "abc-1",
                "item": "3070",
                "item_title": "Multiple values",
                "osm_ids": {"ways": [680900580], "nodes": [], "relations": []},
                "url": "https://osmose.openstreetmap.fr/issue/abc-1",
            }
        ]
        annotate_fixes_with_osmose(fixes, issues)
        assert "osmose_match" in fixes[0]
        assert fixes[0]["osmose_match"]["issue_id"] == "abc-1"
        assert fixes[0]["osmose_match"]["item"] == "3070"
        # Spec: requires_human_review must flip to True after match.
        assert fixes[0]["requires_human_review"] is True

    def test_fix_on_unflagged_way_unchanged(self):
        from osm.osmose import annotate_fixes_with_osmose
        fixes = [
            {
                "kind": "remove_false_oneway",
                "element_type": "way",
                "element_id": 7777,
                "requires_human_review": False,
            }
        ]
        issues = [
            {
                "id": "abc-1",
                "item": "3070",
                "osm_ids": {"ways": [680900580], "nodes": [], "relations": []},
                "url": "https://osmose.openstreetmap.fr/issue/abc-1",
            }
        ]
        annotate_fixes_with_osmose(fixes, issues)
        assert "osmose_match" not in fixes[0]
        assert fixes[0]["requires_human_review"] is False

    def test_empty_issues_is_no_op(self):
        from osm.osmose import annotate_fixes_with_osmose
        fixes = [{"element_type": "way", "element_id": 1, "requires_human_review": False}]
        annotate_fixes_with_osmose(fixes, [])
        assert "osmose_match" not in fixes[0]


# ---------------------------------------------------------------------------
# Integration: review.proposed_fixes_for_way with osmose_index
# ---------------------------------------------------------------------------

class TestReviewIntegration:

    def test_proposed_fixes_for_way_picks_up_osmose_index(self):
        from osm.osmose import index_issues_by_osm_id
        from osm.review import proposed_fixes_for_way

        way = {
            "id": 680900580,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "yes",
            "name_display": "Eastwood Circle",
        }
        issues = [
            {
                "id": "abc-1",
                "item": "3070",
                "item_title": "Multiple values",
                "osm_ids": {"ways": [680900580], "nodes": [], "relations": []},
                "url": "https://osmose.openstreetmap.fr/issue/abc-1",
            }
        ]
        idx = index_issues_by_osm_id(issues)
        fixes = proposed_fixes_for_way(way, osmose_index=idx)
        assert fixes
        assert "osmose_match" in fixes[0]
        assert fixes[0]["requires_human_review"] is True


# ---------------------------------------------------------------------------
# fetch_issues_for_zone
# ---------------------------------------------------------------------------

class TestFetchForZone:

    def test_unknown_zone_raises(self):
        from osm.osmose import fetch_issues_for_zone
        import pytest
        with pytest.raises(KeyError):
            fetch_issues_for_zone("nowhere-zone")
