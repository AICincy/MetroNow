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

    def test_class_a_tertiary_oneway_returns_fix(self):
        # Bug 4: trust the classifier — tertiary+oneway=yes Class A produces a fix.
        way = {
            "id": 500,
            "defect_class": "A",
            "highway": "tertiary",
            "oneway": "yes",
            "name_display": "Maple Pkwy",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert fix["action"] == "remove_tag"
        assert fix["tag"] == "oneway"
        assert fix["element_id"] == 500

    def test_class_a_oneway_minus_one_returns_fix(self):
        # Bug 7: oneway=-1 is a oneway value too; classifier marks it Class A.
        way = {
            "id": 550,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "-1",
            "name_display": "Reverse St",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert fix["element_id"] == 550

    def test_trusts_classifier_no_highway_recheck(self):
        # Bug 4: review.py no longer re-narrows on highway. If the classifier
        # marked something Class A with truthy oneway, the fix proceeds.
        way = {
            "id": 580,
            "defect_class": "A",
            "highway": "primary",  # would have failed the old re-check
            "oneway": "yes",
            "name_display": "Trust Test Rd",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert fix["element_id"] == 580

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
