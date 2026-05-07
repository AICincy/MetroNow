"""Tests for osm.review — proposed fix generation."""

from osm.review import proposed_fix


class TestProposedFix:

    def test_class_a_residential_oneway_returns_fix(self):
        way = {
            "id": 100,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "yes",
            "name_display": "Elm Street",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert fix["action"] == "remove_tag"
        assert fix["tag"] == "oneway"
        assert fix["element_id"] == 100
        assert fix["changes"] == {"oneway": None}

    def test_class_ab_residential_oneway_returns_fix(self):
        way = {
            "id": 200,
            "defect_class": "AB",
            "highway": "residential",
            "oneway": "yes",
            "name_display": "Race Street",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert fix["action"] == "remove_tag"
        assert fix["element_id"] == 200

    def test_class_b_returns_none(self):
        way = {
            "id": 300,
            "defect_class": "B",
            "highway": "residential",
            "oneway": None,
            "name_display": "Vine Street",
        }
        fix = proposed_fix(way)
        assert fix is None

    def test_class_c_returns_none(self):
        way = {
            "id": 400,
            "defect_class": "C",
            "highway": "service",
            "oneway": None,
            "name_display": "Alley",
        }
        fix = proposed_fix(way)
        assert fix is None

    def test_class_a_not_residential_returns_none(self):
        way = {
            "id": 500,
            "defect_class": "A",
            "highway": "primary",
            "oneway": "yes",
            "name_display": "US 50",
        }
        fix = proposed_fix(way)
        assert fix is None

    def test_class_a_oneway_not_yes_returns_none(self):
        way = {
            "id": 600,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "no",
            "name_display": "Quiet Lane",
        }
        fix = proposed_fix(way)
        assert fix is None

    def test_fix_description_contains_way_id(self):
        way = {
            "id": 700,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "yes",
            "name_display": "Central Pkwy",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert "700" in fix["description"]
        assert "Central Pkwy" in fix["description"]
