"""Tests for osm.bus_routes — Phase 4d transit-corridor corroboration."""

from __future__ import annotations


SAMPLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "ROUTE_ID": "4",
                "ROUTE_SHOR": "4",
                "ROUTE_LONG": "Reading Road",
            },
            "geometry": {
                "type": "LineString",
                # 4 vertices along Reading Road, north of Cincinnati.
                "coordinates": [
                    [-84.450, 39.230],
                    [-84.451, 39.235],
                    [-84.452, 39.240],
                    [-84.453, 39.245],
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "ROUTE_ID": "78",
                "ROUTE_SHOR": "78",
                "ROUTE_LONG": "Compton Road",
            },
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [
                    [[-84.55, 39.27], [-84.56, 39.27]],
                    [[-84.57, 39.27], [-84.58, 39.27]],
                ],
            },
        },
    ],
}


class TestParser:

    def test_features_to_bus_routes(self):
        from osm.bus_routes import _features_to_bus_routes
        routes = _features_to_bus_routes(SAMPLE_GEOJSON)
        # MultiLineString explodes into 2 routes (one per ring); plus the
        # single LineString = 3 total.
        assert len(routes) == 3
        ids = [r.route_id for r in routes]
        assert ids.count("4") == 1
        assert ids.count("78") == 2
        # First vertex of route 4 is correctly projected lon→lat to lat,lon.
        r4 = next(r for r in routes if r.route_id == "4")
        assert r4.geometry_latlon[0] == (39.230, -84.450)


class TestTransitCorridorCheck:

    def _routes(self):
        from osm.bus_routes import _features_to_bus_routes
        return _features_to_bus_routes(SAMPLE_GEOJSON)

    def test_way_on_corridor_matches(self):
        # Way midpoint = geom[len/2] = the second vertex below; placed
        # within ~10 m of route 4's vertex at (39.235, -84.451). At
        # this latitude, 0.0001 deg longitude ≈ 8.6 m.
        from osm.bus_routes import is_on_transit_corridor
        way = {
            "type": "way",
            "id": 1,
            "geometry": [
                {"lat": 39.234, "lon": -84.4509},
                {"lat": 39.235, "lon": -84.4509},
                {"lat": 39.236, "lon": -84.4509},
            ],
        }
        on, ids = is_on_transit_corridor(way, self._routes())
        assert on is True
        assert "4" in ids

    def test_way_far_off_corridor_does_not_match(self):
        from osm.bus_routes import is_on_transit_corridor
        way = {
            "type": "way",
            "id": 2,
            "geometry": [
                {"lat": 39.10, "lon": -84.50},
                {"lat": 39.11, "lon": -84.50},
            ],
        }
        on, ids = is_on_transit_corridor(way, self._routes())
        assert on is False
        assert ids == []

    def test_way_with_no_geometry_does_not_match(self):
        from osm.bus_routes import is_on_transit_corridor
        on, ids = is_on_transit_corridor(
            {"type": "way", "id": 3, "geometry": []}, self._routes(),
        )
        assert on is False

    def test_empty_routes_returns_no_match(self):
        from osm.bus_routes import is_on_transit_corridor
        on, ids = is_on_transit_corridor(
            {"type": "way", "id": 4,
             "geometry": [{"lat": 39.234, "lon": -84.451}]},
            [],
        )
        assert on is False


class TestOnewayConflictsCorroboration:
    """detect_oneway_conflicts should annotate findings with
    transit_corridor=True when bus_routes is supplied."""

    def _conflict_pair(self):
        # Two same-name parallel ways with same-direction oneway tags
        # — the canonical conflict pattern. Each has 3 vertices so the
        # mid-vertex (used by corroboration) sits ~10 m from route 4's
        # vertex at (39.235, -84.451).
        return [
            {
                "type": "way",
                "id": 100,
                "tags": {"highway": "tertiary", "name": "Reading Road",
                         "oneway": "yes"},
                "geometry": [
                    {"lat": 39.234, "lon": -84.4509},
                    {"lat": 39.235, "lon": -84.4509},
                    {"lat": 39.236, "lon": -84.4509},
                ],
            },
            {
                "type": "way",
                "id": 101,
                "tags": {"highway": "tertiary", "name": "Reading Road",
                         "oneway": "yes"},
                "geometry": [
                    # ~10 m east, same direction → conflict (not divided).
                    {"lat": 39.234, "lon": -84.4508},
                    {"lat": 39.235, "lon": -84.4508},
                    {"lat": 39.236, "lon": -84.4508},
                ],
            },
        ]

    def test_no_corroboration_without_bus_routes(self):
        from osm.detectors import detect_oneway_conflicts
        out = detect_oneway_conflicts(self._conflict_pair())
        assert out  # detector finds the conflict
        # Without bus_routes, no transit_corridor flag.
        assert "transit_corridor" not in out[0]

    def test_corroboration_with_bus_routes_marks_corridor(self):
        from osm.bus_routes import _features_to_bus_routes
        from osm.detectors import detect_oneway_conflicts
        routes = _features_to_bus_routes(SAMPLE_GEOJSON)
        out = detect_oneway_conflicts(self._conflict_pair(), bus_routes=routes)
        assert out
        # Conflict at ~(39.235, -84.4505); route 4 passes within ~30 m.
        assert out[0].get("transit_corridor") is True
        assert "4" in out[0].get("transit_routes", [])

    def test_off_corridor_pair_not_marked(self):
        from osm.bus_routes import _features_to_bus_routes
        from osm.detectors import detect_oneway_conflicts
        routes = _features_to_bus_routes(SAMPLE_GEOJSON)
        # Same conflict shape but located far from any bus route.
        pair = [
            {
                "type": "way", "id": 200,
                "tags": {"highway": "tertiary", "name": "Far Street",
                         "oneway": "yes"},
                "geometry": [{"lat": 39.10, "lon": -84.30},
                             {"lat": 39.105, "lon": -84.30}],
            },
            {
                "type": "way", "id": 201,
                "tags": {"highway": "tertiary", "name": "Far Street",
                         "oneway": "yes"},
                "geometry": [{"lat": 39.10, "lon": -84.2999},
                             {"lat": 39.105, "lon": -84.2999}],
            },
        ]
        out = detect_oneway_conflicts(pair, bus_routes=routes)
        assert out  # conflict still detected
        assert out[0].get("transit_corridor") is not True
