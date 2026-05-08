"""Tests for osm.gtfs — SORTA GTFS feed loader (Phase 4c)."""

from __future__ import annotations

from unittest import mock


SAMPLE_STOPS_CSV = (
    "stop_id,stop_code,stop_name,stop_desc,stop_lat,stop_lon,zone_id,"
    "stop_url,location_type,parent_station,wheelchair_boarding\n"
    "1435Gal,2773,1435 E Galbraith Westbound,,  39.212009, -84.452934,,,0,,2\n"
    "1438Gal,2774,1438 E Galbraith Eastbound,,  39.211842, -84.452637,,,0,,2\n"
    # Skip station rows (location_type 1)
    "STN1,,Station Entry,,39.10,-84.50,,,1,,0\n"
    # Empty location_type → physical stop (per GTFS spec)
    "EMPTY,,Empty Type,,39.21,-84.45,,,,,2\n"
    # Bad lat/lon → dropped silently
    "BAD,,Bad coords,,not-a-float,whatever,,,0,,2\n"
)


class TestStopsParser:

    def test_parse_stops_skips_non_physical_stops(self):
        from osm.gtfs import parse_stops_csv
        stops = parse_stops_csv(SAMPLE_STOPS_CSV)
        ids = [s.stop_id for s in stops]
        assert "1435Gal" in ids
        assert "1438Gal" in ids
        assert "EMPTY" in ids   # empty location_type ≡ physical stop
        assert "STN1" not in ids   # location_type=1 (station) dropped
        assert "BAD" not in ids    # invalid lat/lon dropped

    def test_parse_stops_strips_whitespace_in_coords(self):
        # SORTA's actual feed has "  39.212009" with leading whitespace.
        from osm.gtfs import parse_stops_csv
        stops = parse_stops_csv(SAMPLE_STOPS_CSV)
        first = next(s for s in stops if s.stop_id == "1435Gal")
        assert abs(first.lat - 39.212009) < 1e-6
        assert abs(first.lon - (-84.452934)) < 1e-6
        assert first.name == "1435 E Galbraith Westbound"


class TestBusStopGtfsCrossCheck:
    """detect_misplaced_bus_stops should suppress findings that match
    a SORTA-published stop position."""

    def _ways(self):
        # Single drivable way ~50 m from the bus stop below (intentionally
        # > 20 m default threshold so the stop would otherwise be flagged).
        return [
            {
                "type": "way",
                "id": 1,
                "tags": {"highway": "residential"},
                "geometry": [
                    {"lat": 39.2125, "lon": -84.4530},
                    {"lat": 39.2125, "lon": -84.4520},
                ],
            },
        ]

    def _bus_stop(self):
        return [
            {
                "type": "node",
                "id": 100,
                "lat": 39.2120,
                "lon": -84.4527,
                "tags": {"highway": "bus_stop", "name": "Test stop"},
            },
        ]

    def test_without_gtfs_flags_misplaced_stop(self):
        from osm.detectors import detect_misplaced_bus_stops
        out = detect_misplaced_bus_stops(self._bus_stop(), self._ways())
        assert len(out) == 1
        assert out[0]["kind"] == "bus_stop_misplaced"
        # Description doesn't mention GTFS when no feed was passed.
        assert "GTFS" not in out[0]["description"]

    def test_gtfs_match_suppresses_finding(self):
        from osm.detectors import detect_misplaced_bus_stops
        from osm.gtfs import GtfsStop
        gtfs = [GtfsStop(stop_id="X", name="Test stop", lat=39.2120, lon=-84.4527)]
        out = detect_misplaced_bus_stops(
            self._bus_stop(), self._ways(), gtfs_stops=gtfs,
        )
        assert out == []

    def test_gtfs_far_away_does_not_suppress(self):
        # GTFS stop ~5 km away → does not suppress; still flagged.
        from osm.detectors import detect_misplaced_bus_stops
        from osm.gtfs import GtfsStop
        gtfs = [GtfsStop(stop_id="X", name="Other stop", lat=39.30, lon=-84.40)]
        out = detect_misplaced_bus_stops(
            self._bus_stop(), self._ways(), gtfs_stops=gtfs,
        )
        assert len(out) == 1
        # Description records that GTFS was consulted.
        assert "GTFS" in out[0]["description"]

    def test_gtfs_match_threshold_is_respected(self):
        from osm.detectors import detect_misplaced_bus_stops
        from osm.gtfs import GtfsStop
        # GTFS stop ~50 m from the OSM stop (just outside default 30 m
        # match threshold).
        gtfs = [GtfsStop(stop_id="X", name="Near", lat=39.21245, lon=-84.4527)]
        out = detect_misplaced_bus_stops(
            self._bus_stop(), self._ways(), gtfs_stops=gtfs,
        )
        # Outside default match threshold → still flagged.
        assert len(out) == 1
        # Loosen the threshold → suppressed.
        out2 = detect_misplaced_bus_stops(
            self._bus_stop(), self._ways(),
            gtfs_stops=gtfs, gtfs_match_threshold_m=100.0,
        )
        assert out2 == []


SAMPLE_MDB_CSV = (
    "mdb_source_id,data_type,location.country_code,provider,"
    "urls.direct_download,urls.latest\n"
    "13,gtfs,US,San Diego MTS,"
    "https://example.com/sd.zip,"
    "https://storage.googleapis.com/sd-13.zip\n"
    "366,gtfs,US,Southwest Ohio Regional Transit Authority (SORTA Metro),"
    "https://www.go-metro.com/uploads/GTFS/google_transit_info.zip,"
    "https://storage.googleapis.com/sorta-366.zip\n"
)


class TestCatalogParser:

    def test_parse_mdb_catalog_finds_sorta(self):
        from urllib.parse import urlparse
        from osm.gtfs import parse_mdb_catalog
        entry = parse_mdb_catalog(SAMPLE_MDB_CSV, source_id="366")
        assert entry is not None
        host = urlparse(entry["direct_download"]).hostname
        assert host == "go-metro.com" or (host is not None and host.endswith(".go-metro.com"))
        assert entry["latest"].endswith("sorta-366.zip")
        assert "SORTA" in entry["provider"]

    def test_parse_mdb_catalog_returns_none_for_unknown(self):
        from osm.gtfs import parse_mdb_catalog
        assert parse_mdb_catalog(SAMPLE_MDB_CSV, source_id="9999") is None

    def test_parse_mdb_catalog_default_source_is_sorta(self):
        from osm.gtfs import parse_mdb_catalog
        entry = parse_mdb_catalog(SAMPLE_MDB_CSV)  # default = "366"
        assert entry is not None
        assert "SORTA" in entry["provider"]


class TestResolveSortaFeedUrl:

    def test_resolves_to_direct_download(self, tmp_path, monkeypatch):
        from osm import gtfs as gtfs_mod
        # Redirect cache to a tmp file so the test doesn't read stale state.
        monkeypatch.setattr(gtfs_mod, "MDB_CACHE", tmp_path / "mdb.json")

        class _Resp:
            text = SAMPLE_MDB_CSV
            def raise_for_status(self): pass

        with mock.patch.object(
            gtfs_mod.requests, "get", autospec=True,
        ) as mreq:
            mreq.return_value = _Resp()
            url = gtfs_mod.resolve_sorta_feed_url(force_refresh=True)
        assert url == "https://www.go-metro.com/uploads/GTFS/google_transit_info.zip"

    def test_falls_back_on_network_failure(self, tmp_path, monkeypatch):
        from osm import gtfs as gtfs_mod
        monkeypatch.setattr(gtfs_mod, "MDB_CACHE", tmp_path / "mdb.json")
        with mock.patch.object(
            gtfs_mod.requests, "get", autospec=True,
        ) as mreq:
            mreq.side_effect = gtfs_mod.requests.RequestException("offline")
            url = gtfs_mod.resolve_sorta_feed_url(force_refresh=True)
        assert url == gtfs_mod.SORTA_GTFS_URL

    def test_falls_back_when_source_id_missing(self, tmp_path, monkeypatch):
        from osm import gtfs as gtfs_mod
        monkeypatch.setattr(gtfs_mod, "MDB_CACHE", tmp_path / "mdb.json")
        # CSV with no row 366
        bad_csv = (
            "mdb_source_id,data_type,provider,"
            "urls.direct_download,urls.latest\n"
            "13,gtfs,Other,https://other.example/feed.zip,\n"
        )

        class _Resp:
            text = bad_csv
            def raise_for_status(self): pass

        with mock.patch.object(
            gtfs_mod.requests, "get", autospec=True,
        ) as mreq:
            mreq.return_value = _Resp()
            url = gtfs_mod.resolve_sorta_feed_url(force_refresh=True)
        assert url == gtfs_mod.SORTA_GTFS_URL

    def test_uses_cache_when_fresh(self, tmp_path, monkeypatch):
        import json as _json

        from osm import gtfs as gtfs_mod
        cache = tmp_path / "mdb.json"
        cache.write_text(_json.dumps({
            "direct_download": "https://cached.example/sorta.zip",
            "latest": "",
            "provider": "SORTA",
        }))
        monkeypatch.setattr(gtfs_mod, "MDB_CACHE", cache)
        # Network mock to ensure it's NOT called.
        with mock.patch.object(
            gtfs_mod.requests, "get", autospec=True,
        ) as mreq:
            url = gtfs_mod.resolve_sorta_feed_url()
            assert mreq.call_count == 0
        assert url == "https://cached.example/sorta.zip"
