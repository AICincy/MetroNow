"""Tests for osm.maproulette — Phase 3 task generator."""

from __future__ import annotations

import json


def _classified_with(ways: list[dict]) -> dict:
    return {"all_ways": ways}


class TestUnverifiedClassA:

    def test_includes_class_a_without_cagis(self):
        from osm.maproulette import unverified_class_a_ways
        ways = [
            {
                "id": 1, "defect_class": "A", "name": "Maple St",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
                "cagis_match": None,
            },
        ]
        out = unverified_class_a_ways(_classified_with(ways))
        assert [w["id"] for w in out] == [1]

    def test_includes_class_ab(self):
        from osm.maproulette import unverified_class_a_ways
        ways = [
            {
                "id": 2, "defect_class": "AB", "name": "Compound Way",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
                "cagis_match": {"confidence": 0.5},
            },
        ]
        assert len(unverified_class_a_ways(_classified_with(ways))) == 1

    def test_excludes_high_confidence_cagis(self):
        # ≥ HIGH_CONFIDENCE goes through auto-submit, not MapRoulette.
        from osm.maproulette import unverified_class_a_ways
        ways = [
            {
                "id": 3, "defect_class": "A", "name": "Auto",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
                "cagis_match": {"confidence": 0.92},
            },
        ]
        assert unverified_class_a_ways(_classified_with(ways)) == []

    def test_excludes_class_b_and_c(self):
        from osm.maproulette import unverified_class_a_ways
        ways = [
            {
                "id": 4, "defect_class": "B", "name": "B way",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
            },
            {
                "id": 5, "defect_class": "C", "name": "C way",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
            },
        ]
        assert unverified_class_a_ways(_classified_with(ways)) == []

    def test_excludes_ways_without_geometry(self):
        from osm.maproulette import unverified_class_a_ways
        ways = [
            {"id": 6, "defect_class": "A", "name": "No geom", "geometry": []},
        ]
        assert unverified_class_a_ways(_classified_with(ways)) == []


class TestBuildTasks:

    def test_priority_orders_ab_above_a(self):
        from osm.maproulette import (
            PRIORITY_HIGH,
            PRIORITY_MEDIUM,
            build_tasks,
        )
        tasks = build_tasks([
            {"id": 1, "defect_class": "A", "name": "A",
             "geometry": [[39.2, -84.4], [39.21, -84.4]]},
            {"id": 2, "defect_class": "AB", "name": "AB",
             "geometry": [[39.2, -84.4], [39.21, -84.4]]},
        ])
        by_id = {t.way_id: t for t in tasks}
        assert by_id[2].priority == PRIORITY_HIGH
        assert by_id[1].priority == PRIORITY_MEDIUM

    def test_instruction_mentions_cagis_when_present(self):
        from osm.maproulette import build_tasks
        tasks = build_tasks([
            {
                "id": 99, "defect_class": "AB",
                "name": "Test St", "oneway": "yes",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
                "cagis_match": {
                    "confidence": 0.72, "cagis_id": 42,
                    "cagis_oneway": "no",
                },
            },
        ])
        instr = tasks[0].instruction
        assert "0.72" in instr
        assert "REVIEW band" in instr
        assert "42" in instr
        assert "openstreetmap.org/way/99" in instr

    def test_instruction_explains_no_cagis_match(self):
        from osm.maproulette import build_tasks
        tasks = build_tasks([
            {
                "id": 100, "defect_class": "A",
                "name": "Lonely Lane", "oneway": "yes",
                "geometry": [[39.2, -84.4], [39.21, -84.4]],
                "cagis_match": None,
            },
        ])
        instr = tasks[0].instruction
        assert "No CAGIS centerline" in instr


class TestGeoJSONOutput:

    def test_feature_uses_lon_lat_order(self):
        from osm.maproulette import build_tasks, task_to_feature
        tasks = build_tasks([
            {"id": 1, "defect_class": "A", "name": "Test",
             "geometry": [[39.2, -84.4], [39.21, -84.39]]},
        ])
        feat = task_to_feature(tasks[0])
        # OSM is [lat, lon]; GeoJSON output must be [lon, lat].
        assert feat["geometry"]["type"] == "LineString"
        assert feat["geometry"]["coordinates"][0] == [-84.4, 39.2]
        assert feat["geometry"]["coordinates"][1] == [-84.39, 39.21]

    def test_feature_carries_way_id_and_link(self):
        from osm.maproulette import build_tasks, task_to_feature
        tasks = build_tasks([
            {"id": 4242, "defect_class": "AB", "name": "X",
             "geometry": [[39.2, -84.4], [39.21, -84.4]]},
        ])
        f = task_to_feature(tasks[0])
        assert f["properties"]["way_id"] == 4242
        assert f["properties"]["osm_link"].endswith("/way/4242")
        assert "Class AB" in f["properties"]["task_name"]

    def test_write_geojsonl_emits_one_line_per_task(self, tmp_path):
        from osm.maproulette import build_tasks, write_geojsonl
        tasks = build_tasks([
            {"id": 1, "defect_class": "A", "name": "A",
             "geometry": [[39.2, -84.4], [39.21, -84.4]]},
            {"id": 2, "defect_class": "AB", "name": "AB",
             "geometry": [[39.2, -84.4], [39.21, -84.4]]},
        ])
        out = tmp_path / "x" / "tasks.geojsonl"
        n = write_geojsonl(tasks, out)
        assert n == 2
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        # Every line is parseable JSON.
        for line in lines:
            obj = json.loads(line)
            assert obj["type"] == "Feature"
            assert obj["geometry"]["type"] == "LineString"


class TestChallengeMetadata:

    def test_metadata_includes_zone_and_count(self):
        from osm.maproulette import challenge_metadata
        m = challenge_metadata(
            zone_name="Blue Ash / Montgomery",
            zone_key="blue-ash-montgomery",
            n_tasks=42,
        )
        assert "Blue Ash / Montgomery" in m["name"]
        assert "42" in m["description"]
        assert "blue-ash-montgomery" in m["checkin_comment"]
        assert "tiger" in m["tags"]


class TestGapTasks:
    """Phase 3 follow-up: node-disconnect gap → MapRoulette task."""

    def _classified_with_gaps(self):
        return {
            "gaps": [
                {
                    "lat": 39.232, "lon": -84.378,
                    "street": "Oak Street", "type": "probable_disconnect",
                    "way1_id": 100, "way2_id": 200, "distance_m": 19.8,
                },
                {
                    "lat": 39.245, "lon": -84.385,
                    "street": "Maple Lane", "type": "probable_disconnect",
                    "way1_id": 300, "way2_id": 400, "distance_m": 22.4,
                },
                # Bad coords → dropped silently.
                {
                    "lat": None, "lon": -84.3,
                    "street": "Bad", "way1_id": 500, "way2_id": 600,
                },
            ],
        }

    def test_unverified_gaps_filters_bad_coords(self):
        from osm.maproulette import unverified_gaps
        out = unverified_gaps(self._classified_with_gaps())
        assert len(out) == 2
        assert {g["street"] for g in out} == {"Oak Street", "Maple Lane"}

    def test_build_gap_tasks_carries_distance_and_ids(self):
        from osm.maproulette import build_gap_tasks, unverified_gaps
        gaps = unverified_gaps(self._classified_with_gaps())
        tasks = build_gap_tasks(gaps)
        assert len(tasks) == 2
        oak = next(t for t in tasks if t.street == "Oak Street")
        assert oak.way1_id == 100
        assert oak.way2_id == 200
        assert oak.distance_m == 19.8
        assert "openstreetmap.org/way/100" in oak.instruction
        assert "openstreetmap.org/way/200" in oak.instruction
        assert "19.8 m" in oak.instruction

    def test_gap_task_to_feature_uses_point_geometry(self):
        from osm.maproulette import build_gap_tasks, gap_task_to_feature
        gaps = [
            {"lat": 39.232, "lon": -84.378, "street": "X",
             "way1_id": 1, "way2_id": 2, "distance_m": 12.5},
        ]
        feat = gap_task_to_feature(build_gap_tasks(gaps)[0])
        assert feat["geometry"]["type"] == "Point"
        # GeoJSON is [lon, lat] — confirm we project correctly.
        assert feat["geometry"]["coordinates"] == [-84.378, 39.232]
        assert feat["properties"]["way1_id"] == 1
        assert feat["properties"]["way2_id"] == 2
        assert feat["properties"]["distance_m"] == 12.5

    def test_write_gap_geojsonl_emits_one_line_per_task(self, tmp_path):
        import json as _json
        from osm.maproulette import build_gap_tasks, write_gap_geojsonl
        tasks = build_gap_tasks([
            {"lat": 39.232, "lon": -84.378, "street": "A",
             "way1_id": 1, "way2_id": 2, "distance_m": 10},
            {"lat": 39.234, "lon": -84.379, "street": "B",
             "way1_id": 3, "way2_id": 4, "distance_m": 25},
        ])
        out = tmp_path / "gaps.geojsonl"
        n = write_gap_geojsonl(tasks, out)
        assert n == 2
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        for line in lines:
            obj = _json.loads(line)
            assert obj["geometry"]["type"] == "Point"
            assert "way1_id" in obj["properties"]

    def test_gap_challenge_metadata_uses_node_disconnect_tag(self):
        from osm.maproulette import gap_challenge_metadata
        m = gap_challenge_metadata(
            zone_name="Blue Ash / Montgomery",
            zone_key="blue-ash-montgomery",
            n_tasks=238,
        )
        assert "node disconnects" in m["name"]
        assert "238" in m["description"]
        assert "node_disconnect" in m["tags"]
