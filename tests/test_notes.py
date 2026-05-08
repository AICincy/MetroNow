"""Tests for osm.notes — OSM Notes fetcher and finding-annotator."""

from __future__ import annotations

import json
import time
from unittest import mock


# ---------------------------------------------------------------------------
# Sample OSM Notes API GeoJSON (mirrors the real schema observed 2026-05-08)
# ---------------------------------------------------------------------------

def _sample_feature_collection() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-84.3550658, 39.2249645],
                },
                "properties": {
                    "id": 5215840,
                    "url": "https://api.openstreetmap.org/api/0.6/notes/5215840.json",
                    "status": "open",
                    "date_created": "2026-03-22 12:34:56 UTC",
                    "comments": [
                        {
                            "date": "2026-03-22 12:34:56 UTC",
                            "user": "anonymous",
                            "action": "opened",
                            "text": "Stop sign missing at this junction.",
                        },
                    ],
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-84.0, 39.5],
                },
                "properties": {
                    "id": 9999,
                    "status": "open",
                    "date_created": "2024-01-01 00:00:00 UTC",
                    "comments": [],
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize:

    def test_normalize_real_blue_ash_note_shape(self):
        from osm.notes import _normalize_note
        feat = _sample_feature_collection()["features"][0]
        n = _normalize_note(feat)
        assert n is not None
        assert n["id"] == 5215840
        assert n["lat"] == 39.2249645
        assert n["lon"] == -84.3550658
        assert n["status"] == "open"
        assert n["date_created"].startswith("2026-03-22")
        assert len(n["comments"]) == 1
        assert n["comments"][0]["user"] == "anonymous"
        assert "Stop sign" in n["comments"][0]["text"]
        assert "5215840" in n["url"]

    def test_normalize_drops_feature_without_coords(self):
        from osm.notes import _normalize_note
        bad = {"type": "Feature", "geometry": {"coordinates": []}, "properties": {"id": 1}}
        assert _normalize_note(bad) is None

    def test_normalize_drops_feature_without_id(self):
        from osm.notes import _normalize_note
        bad = {
            "type": "Feature",
            "geometry": {"coordinates": [-84.0, 39.0]},
            "properties": {},
        }
        assert _normalize_note(bad) is None


# ---------------------------------------------------------------------------
# fetch_notes — patched HTTP
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


class TestFetchNotes:

    def test_fetch_notes_normalizes_response(self, tmp_path, monkeypatch):
        from osm import notes as notes_mod
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path)

        sample = _sample_feature_collection()
        with mock.patch("osm.notes.requests.get", return_value=_MockResponse(sample)) as m:
            result = notes_mod.fetch_notes(
                (39.16, -84.44, 39.24, -84.33), force_refresh=True
            )
        # Ensure the URL passed to requests.get used the expected bbox order
        # (lon-min,lat-min,lon-max,lat-max).
        assert m.call_count == 1
        call_url = m.call_args[0][0]
        assert "-84.44%2C39.16%2C-84.33%2C39.24" in call_url or "-84.44,39.16,-84.33,39.24" in call_url
        # closed=0 is what we asked for (status='open' default).
        assert "closed=0" in call_url
        assert len(result) == 2
        assert result[0]["id"] == 5215840

    def test_empty_bbox_returns_empty(self, tmp_path, monkeypatch):
        from osm import notes as notes_mod
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path)
        empty = {"type": "FeatureCollection", "features": []}
        with mock.patch("osm.notes.requests.get", return_value=_MockResponse(empty)):
            result = notes_mod.fetch_notes(
                (39.0, -85.0, 39.01, -84.99), force_refresh=True
            )
        assert result == []

    def test_malformed_response_returns_empty(self, tmp_path, monkeypatch):
        from osm import notes as notes_mod
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path)
        bogus = {"not": "geojson"}
        with mock.patch("osm.notes.requests.get", return_value=_MockResponse(bogus)):
            result = notes_mod.fetch_notes(
                (39.0, -85.0, 39.01, -84.99), force_refresh=True
            )
        assert result == []

    def test_http_error_returns_empty(self, tmp_path, monkeypatch):
        from osm import notes as notes_mod
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path)
        import requests
        with mock.patch(
            "osm.notes.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ):
            result = notes_mod.fetch_notes(
                (39.0, -85.0, 39.01, -84.99), force_refresh=True
            )
        assert result == []

    def test_cache_ttl_respected(self, tmp_path, monkeypatch):
        """A fresh cache file under TTL is read directly; the network is
        NOT touched a second time."""
        from osm import notes as notes_mod
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path)

        sample = _sample_feature_collection()
        with mock.patch(
            "osm.notes.requests.get", return_value=_MockResponse(sample)
        ) as m:
            first = notes_mod.fetch_notes(
                (39.16, -84.44, 39.24, -84.33), force_refresh=True
            )
            # Immediately re-read — the cache file is fresh, so requests.get
            # should not be called again.
            second = notes_mod.fetch_notes(
                (39.16, -84.44, 39.24, -84.33), force_refresh=False
            )
        assert m.call_count == 1
        assert len(first) == len(second) == 2

    def test_cache_ttl_expired_refetches(self, tmp_path, monkeypatch):
        """A cache file older than the TTL triggers a re-fetch."""
        from osm import notes as notes_mod
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_DIR", tmp_path)
        # Force tiny TTL so we don't have to fast-forward the clock.
        monkeypatch.setattr(notes_mod, "NOTES_CACHE_TTL_S", 1)

        sample = _sample_feature_collection()
        with mock.patch(
            "osm.notes.requests.get", return_value=_MockResponse(sample)
        ) as m:
            notes_mod.fetch_notes(
                (39.16, -84.44, 39.24, -84.33), force_refresh=True
            )
            # Age the cache file beyond TTL.
            for p in tmp_path.glob("*.json"):
                old = time.time() - 5
                import os
                os.utime(p, (old, old))
            notes_mod.fetch_notes((39.16, -84.44, 39.24, -84.33))
        assert m.call_count == 2


# ---------------------------------------------------------------------------
# annotate_findings_with_notes
# ---------------------------------------------------------------------------

def _real_blue_ash_note() -> dict:
    return {
        "id": 5215840,
        "lat": 39.2249645,
        "lon": -84.3550658,
        "status": "open",
        "date_created": "2026-03-22 12:34:56 UTC",
        "comments": [{"text": "Stop sign missing.", "user": "anonymous"}],
        "url": "https://www.openstreetmap.org/note/5215840",
    }


class TestAnnotate:

    def test_finding_within_50m_of_real_note_gets_annotated(self):
        from osm.notes import annotate_findings_with_notes
        # The real Blue Ash note sits at (39.2249645, -84.3550658). Our
        # finding is ~6.9 m away — well inside the 50 m default threshold
        # the spec calls for.
        findings = [{"kind": "x", "lat": 39.225, "lon": -84.355, "id": 1}]
        notes = [_real_blue_ash_note()]
        annotate_findings_with_notes(findings, notes, threshold_m=50.0)
        assert "near_note" in findings[0]
        assert findings[0]["near_note"]["id"] == 5215840
        assert findings[0]["near_note"]["distance_m"] < 50.0

    def test_threshold_10m_loses_annotation(self):
        from osm.notes import annotate_findings_with_notes
        # ~37.7 m away from the real Blue Ash note: inside the 50 m default
        # threshold, but outside a tight 10 m one. Confirms the threshold_m
        # parameter actually narrows what gets attached.
        findings = [{"kind": "x", "lat": 39.2253, "lon": -84.355, "id": 1}]
        notes = [_real_blue_ash_note()]
        annotate_findings_with_notes(findings, notes, threshold_m=10.0)
        assert "near_note" not in findings[0]
        # And confirm the same point at 50 m DOES get annotated.
        annotate_findings_with_notes(findings, notes, threshold_m=50.0)
        assert findings[0].get("near_note", {}).get("id") == 5215840

    def test_only_open_notes_attached(self):
        from osm.notes import annotate_findings_with_notes
        closed_note = {
            **_real_blue_ash_note(),
            "status": "closed",
            "date_closed": "2024-01-01",
        }
        findings = [{"kind": "x", "lat": 39.225, "lon": -84.355, "id": 1}]
        annotate_findings_with_notes(findings, [closed_note], threshold_m=50.0)
        assert "near_note" not in findings[0]

    def test_finding_without_coords_unchanged(self):
        from osm.notes import annotate_findings_with_notes
        findings = [{"kind": "x", "id": 1}]
        annotate_findings_with_notes(findings, [_real_blue_ash_note()])
        assert "near_note" not in findings[0]

    def test_picks_most_recent_note_when_multiple_in_range(self):
        from osm.notes import annotate_findings_with_notes
        older = {
            **_real_blue_ash_note(),
            "id": 1,
            "date_created": "2020-01-01",
        }
        newer = {
            **_real_blue_ash_note(),
            "id": 2,
            "date_created": "2026-04-01",
        }
        findings = [{"kind": "x", "lat": 39.225, "lon": -84.355, "id": 1}]
        annotate_findings_with_notes(findings, [older, newer], threshold_m=50.0)
        assert findings[0]["near_note"]["id"] == 2


# ---------------------------------------------------------------------------
# fetch_notes_for_zone
# ---------------------------------------------------------------------------

class TestFetchForZone:

    def test_unknown_zone_raises(self):
        from osm.notes import fetch_notes_for_zone
        import pytest
        with pytest.raises(KeyError):
            fetch_notes_for_zone("nowhere-zone")
