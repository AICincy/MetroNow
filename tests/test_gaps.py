"""Tests for osm.gaps — endpoint disconnect detection and clustering."""

from osm.gaps import detect_gaps


def _make_way_record(way_id, start_latlon, end_latlon):
    """Build a minimal way record with geometry endpoints."""
    return {
        "id": way_id,
        "name": "Test Street",
        "geometry": [list(start_latlon), list(end_latlon)],
    }


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

class TestDetectGaps:

    def test_close_endpoints_detected(self):
        """Two ways with endpoints ~10 m apart should produce a gap."""
        # ~10 m apart at Cincinnati's latitude
        w1 = _make_way_record(1, (39.1000, -84.5000), (39.1001, -84.5000))
        w2 = _make_way_record(2, (39.10019, -84.5000), (39.1003, -84.5000))
        streets = {"Test Street": [w1, w2]}
        gaps = detect_gaps(streets)
        assert len(gaps) >= 1
        assert gaps[0]["distance_m"] < 30.0
        assert gaps[0]["street"] == "Test Street"

    def test_far_endpoints_no_gap(self):
        """Two ways with endpoints ~100 m apart should produce no gap."""
        w1 = _make_way_record(1, (39.1000, -84.5000), (39.1001, -84.5000))
        w2 = _make_way_record(2, (39.1010, -84.5000), (39.1020, -84.5000))
        streets = {"Test Street": [w1, w2]}
        gaps = detect_gaps(streets)
        assert len(gaps) == 0

    def test_touching_endpoints_no_gap(self):
        """Endpoints at the same point (d < 0.01 m) are connected, not a gap."""
        w1 = _make_way_record(1, (39.1000, -84.5000), (39.1005, -84.5000))
        w2 = _make_way_record(2, (39.1005, -84.5000), (39.1010, -84.5000))
        streets = {"Test Street": [w1, w2]}
        gaps = detect_gaps(streets)
        assert len(gaps) == 0

    def test_gap_includes_way_ids(self):
        """Gap records should reference the two involved ways."""
        w1 = _make_way_record(10, (39.1000, -84.5000), (39.10015, -84.5000))
        w2 = _make_way_record(20, (39.10018, -84.5000), (39.1003, -84.5000))
        streets = {"Test Street": [w1, w2]}
        gaps = detect_gaps(streets)
        assert len(gaps) >= 1
        assert gaps[0]["way1_id"] == 10
        assert gaps[0]["way2_id"] == 20

    def test_empty_streets_no_gaps(self):
        assert detect_gaps({}) == []


# ---------------------------------------------------------------------------
# Junction clustering
# ---------------------------------------------------------------------------

class TestJunctionClustering:

    def test_gaps_within_5m_collapsed(self):
        """Multiple gaps at nearly the same location should collapse to one."""
        # Three ways forming a junction with ~5 m gaps between each pair.
        # All gap midpoints will be within GAP_CLUSTER_M (5m) of each other.
        base_lat = 39.1000
        base_lon = -84.5000
        offset = 0.00005  # ~5 m at this latitude

        w1 = _make_way_record(1, (base_lat, base_lon), (base_lat + offset, base_lon))
        w2 = _make_way_record(
            2,
            (base_lat + offset + 0.00003, base_lon),
            (base_lat + 2 * offset, base_lon),
        )
        w3 = _make_way_record(
            3,
            (base_lat + offset + 0.00004, base_lon),
            (base_lat + 3 * offset, base_lon),
        )
        streets = {"Test Street": [w1, w2, w3]}
        gaps = detect_gaps(streets)
        # Without clustering we'd get up to 3 gap records (1-2, 1-3, 2-3).
        # Clustering within 5 m should collapse them.
        assert len(gaps) <= 2
