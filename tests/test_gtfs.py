"""Tests for osm.gtfs — SORTA GTFS feed loader (Phase 4c)."""

from __future__ import annotations


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
