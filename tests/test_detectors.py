"""Tests for osm.detectors — rider-impact defect detectors.

Each detector gets at least one positive case (should fire) and one
negative case (should not fire). Fakes use the Overpass element shape
(``type``, ``id``, ``tags``, plus ``geometry`` for ways and ``lat``/
``lon`` for nodes) so the same fixtures can be passed straight to the
classifier in integration smoke tests.
"""

from __future__ import annotations

from osm.detectors import (
    detect_access_blocked_residential,
    detect_arterial_named_residential,
    detect_barriers_without_access,
    detect_broken_turn_restrictions,
    detect_misplaced_bus_stops,
    detect_missing_maxspeed_arterial,
    detect_oneway_conflicts,
    detect_oneway_minus_one,
)

# --- helpers --------------------------------------------------------------

def _way(way_id, tags, geom):
    """Build a fake Overpass way."""
    return {
        "type": "way",
        "id": way_id,
        "tags": tags,
        "geometry": [{"lat": lat, "lon": lon} for lat, lon in geom],
    }


def _node(node_id, lat, lon, tags):
    return {
        "type": "node",
        "id": node_id,
        "lat": lat,
        "lon": lon,
        "tags": tags,
    }


def _restriction(rel_id, tags, members):
    return {
        "type": "relation",
        "id": rel_id,
        "tags": tags,
        "members": members,
    }


# --- detect_oneway_minus_one ---------------------------------------------

class TestOnewayMinusOne:
    def test_residential_minus_one_flagged(self):
        ways = [_way(1, {"highway": "residential", "oneway": "-1"}, [(0, 0), (0, 0.001)])]
        out = detect_oneway_minus_one(ways)
        assert len(out) == 1
        assert out[0]["kind"] == "oneway_minus_one"
        assert out[0]["id"] == 1

    def test_oneway_yes_not_flagged(self):
        ways = [_way(2, {"highway": "residential", "oneway": "yes"}, [(0, 0), (0, 0.001)])]
        assert detect_oneway_minus_one(ways) == []

    def test_primary_minus_one_outside_class_a_set(self):
        # highway=primary is not in CLASS_A_HIGHWAYS so we don't flag it.
        ways = [_way(3, {"highway": "primary", "oneway": "-1"}, [(0, 0), (0, 0.001)])]
        assert detect_oneway_minus_one(ways) == []


# --- detect_oneway_conflicts ---------------------------------------------

class TestOnewayConflicts:
    def test_same_direction_oneways_flagged(self):
        # Two ways with the same name, both oneway=yes, geometries ~11 m
        # apart in lat (perpendicularly offset), pointing the SAME way —
        # defect pattern (a). One was digitised the wrong way round.
        a = _way(
            10, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10000, -84.50), (39.10000, -84.499)],
        )
        b = _way(
            11, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10010, -84.50), (39.10010, -84.499)],
        )
        out = detect_oneway_conflicts([a, b])
        assert len(out) == 1
        assert out[0]["kind"] == "oneway_conflict"

    def test_legitimate_divided_carriageway_not_flagged(self):
        # Two ways same name, both oneway=yes, ~11 m apart, pointing in
        # OPPOSITE directions — a normal divided carriageway, NOT a defect.
        a = _way(
            12, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10000, -84.50), (39.10000, -84.499)],
        )
        b = _way(
            13, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10010, -84.499), (39.10010, -84.50)],
        )
        assert detect_oneway_conflicts([a, b]) == []

    def test_minus_one_aligned_with_yes_flagged(self):
        # Defect pattern (b): one oneway=yes and one oneway=-1, parallel-
        # paired at ~11 m offset, but their *effective* direction vectors
        # point the same way.
        # Way a: drawn 0->0.001, oneway=yes => effective dir = +lon.
        # Way b: drawn 0.001->0, oneway=-1 => effective dir = +lon (negated).
        a = _way(
            14, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10000, -84.50), (39.10000, -84.499)],
        )
        b = _way(
            15, {"highway": "residential", "name": "Main", "oneway": "-1"},
            [(39.10010, -84.499), (39.10010, -84.50)],
        )
        out = detect_oneway_conflicts([a, b])
        assert len(out) == 1
        assert out[0]["kind"] == "oneway_conflict"

    def test_far_apart_not_flagged(self):
        a = _way(
            16, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10000, -84.50), (39.10000, -84.499)],
        )
        b = _way(
            17, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.20000, -84.50), (39.20000, -84.499)],
        )
        assert detect_oneway_conflicts([a, b]) == []

    def test_chained_sequential_segments_not_flagged(self):
        # Two segments of the same physical oneway street, joined at a
        # shared endpoint. Both oneway=yes, both pointing the same direction
        # (because they're chained along the same road). NOT a defect — the
        # parallel-paired check should reject them.
        a = _way(
            18, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10, -84.500), (39.10, -84.499)],
        )
        b = _way(
            19, {"highway": "residential", "name": "Main", "oneway": "yes"},
            [(39.10, -84.499), (39.10, -84.498)],
        )
        assert detect_oneway_conflicts([a, b]) == []


# --- detect_access_blocked_residential ------------------------------------

class TestAccessBlocked:
    def test_access_private_flagged(self):
        ways = [_way(20, {"highway": "residential", "access": "private"}, [(0, 0), (0, 0.001)])]
        out = detect_access_blocked_residential(ways)
        assert len(out) == 1 and out[0]["kind"] == "access_blocked"

    def test_motor_vehicle_destination_skipped(self):
        ways = [_way(
            21,
            {"highway": "residential", "access": "private", "motor_vehicle": "destination"},
            [(0, 0), (0, 0.001)],
        )]
        assert detect_access_blocked_residential(ways) == []

    def test_no_access_tag_not_flagged(self):
        ways = [_way(22, {"highway": "residential"}, [(0, 0), (0, 0.001)])]
        assert detect_access_blocked_residential(ways) == []

    def test_service_with_access_private_not_flagged(self):
        # Driveways/parking aisles tagged highway=service legitimately use
        # access=private and are NOT what a rider would expect to traverse.
        ways = [_way(
            23, {"highway": "service", "access": "private"},
            [(0, 0), (0, 0.001)],
        )]
        assert detect_access_blocked_residential(ways) == []


# --- detect_barriers_without_access --------------------------------------

class TestBarriers:
    def test_unqualified_gate_flagged(self):
        nodes = [_node(30, 39.1, -84.5, {"barrier": "gate"})]
        out = detect_barriers_without_access(nodes)
        assert len(out) == 1 and out[0]["kind"] == "barrier_unqualified"

    def test_qualified_gate_not_flagged(self):
        nodes = [_node(31, 39.1, -84.5, {"barrier": "gate", "access": "yes"})]
        assert detect_barriers_without_access(nodes) == []

    def test_unknown_barrier_not_flagged(self):
        nodes = [_node(32, 39.1, -84.5, {"barrier": "fence"})]
        assert detect_barriers_without_access(nodes) == []


# --- detect_broken_turn_restrictions -------------------------------------

class TestBrokenTurnRestrictions:
    def test_missing_via_role_flagged(self):
        rel = _restriction(
            40,
            {"type": "restriction", "restriction": "no_left_turn"},
            [
                {"role": "from", "ref": 1, "type": "way"},
                {"role": "to", "ref": 2, "type": "way"},
            ],
        )
        out = detect_broken_turn_restrictions([rel])
        assert len(out) == 1
        assert "missing roles" in out[0]["description"]

    def test_empty_restriction_tag_flagged(self):
        rel = _restriction(
            41,
            {"type": "restriction", "restriction": ""},
            [
                {"role": "from", "ref": 1, "type": "way"},
                {"role": "via", "ref": 9, "type": "node"},
                {"role": "to", "ref": 2, "type": "way"},
            ],
        )
        out = detect_broken_turn_restrictions([rel])
        assert len(out) == 1

    def test_complete_restriction_passes(self):
        rel = _restriction(
            42,
            {"type": "restriction", "restriction": "no_u_turn"},
            [
                {"role": "from", "ref": 1, "type": "way"},
                {"role": "via", "ref": 9, "type": "node"},
                {"role": "to", "ref": 2, "type": "way"},
            ],
        )
        assert detect_broken_turn_restrictions([rel]) == []


# --- detect_arterial_named_residential -----------------------------------

class TestArterialNamedResidential:
    def test_boulevard_flagged(self):
        ways = [_way(50, {"highway": "residential", "name": "Reading Boulevard"}, [(0, 0), (0, 0.001)])]
        out = detect_arterial_named_residential(ways)
        assert len(out) == 1 and out[0]["kind"] == "arterial_named_residential"

    def test_pike_flagged(self):
        ways = [_way(51, {"highway": "residential", "name": "Mason Pike"}, [(0, 0), (0, 0.001)])]
        assert len(detect_arterial_named_residential(ways)) == 1

    def test_residential_normal_name_not_flagged(self):
        ways = [_way(52, {"highway": "residential", "name": "Elm Street"}, [(0, 0), (0, 0.001)])]
        assert detect_arterial_named_residential(ways) == []

    def test_primary_with_boulevard_not_flagged(self):
        # Already classified arterial, not a residential mistake.
        ways = [_way(53, {"highway": "primary", "name": "Reading Boulevard"}, [(0, 0), (0, 0.001)])]
        assert detect_arterial_named_residential(ways) == []


# --- detect_missing_maxspeed_arterial ------------------------------------

class TestMissingMaxspeed:
    def test_tertiary_no_maxspeed_flagged(self):
        ways = [_way(60, {"highway": "tertiary"}, [(0, 0), (0, 0.001)])]
        out = detect_missing_maxspeed_arterial(ways)
        assert len(out) == 1 and out[0]["kind"] == "missing_maxspeed"

    def test_residential_not_flagged(self):
        ways = [_way(61, {"highway": "residential"}, [(0, 0), (0, 0.001)])]
        assert detect_missing_maxspeed_arterial(ways) == []

    def test_with_maxspeed_not_flagged(self):
        ways = [_way(62, {"highway": "tertiary", "maxspeed": "35 mph"}, [(0, 0), (0, 0.001)])]
        assert detect_missing_maxspeed_arterial(ways) == []

    def test_secondary_not_flagged(self):
        # Secondary/primary/trunk legitimately omit maxspeed (signage tells
        # the driver) and were dominating the finding list with noise.
        ways = [_way(63, {"highway": "secondary"}, [(0, 0), (0, 0.001)])]
        assert detect_missing_maxspeed_arterial(ways) == []

    def test_primary_not_flagged(self):
        ways = [_way(64, {"highway": "primary"}, [(0, 0), (0, 0.001)])]
        assert detect_missing_maxspeed_arterial(ways) == []


# --- detect_misplaced_bus_stops ------------------------------------------

class TestMisplacedBusStops:
    def test_distant_bus_stop_flagged(self):
        # Bus stop ~111 m from any drivable vertex.
        stops = [_node(70, 39.105, -84.50, {"highway": "bus_stop"})]
        ways = [_way(71, {"highway": "residential"}, [(39.10, -84.50), (39.10, -84.499)])]
        out = detect_misplaced_bus_stops(stops, ways, threshold_m=20.0)
        assert len(out) == 1 and out[0]["kind"] == "bus_stop_misplaced"

    def test_close_bus_stop_not_flagged(self):
        stops = [_node(72, 39.10, -84.500001, {"highway": "bus_stop"})]
        ways = [_way(73, {"highway": "residential"}, [(39.10, -84.50), (39.10, -84.499)])]
        assert detect_misplaced_bus_stops(stops, ways, threshold_m=20.0) == []

    def test_parking_aisle_skipped_so_stop_flagged(self):
        # Even though there's a service=parking_aisle vertex right next to
        # the stop, that vertex doesn't count and the stop is otherwise far.
        stops = [_node(74, 39.10, -84.500001, {"highway": "bus_stop"})]
        ways = [_way(
            75,
            {"highway": "service", "service": "parking_aisle"},
            [(39.10, -84.50), (39.10, -84.4999)],
        )]
        out = detect_misplaced_bus_stops(stops, ways, threshold_m=20.0)
        # No real drivable vertices, so detector returns [] (early exit).
        assert out == []
