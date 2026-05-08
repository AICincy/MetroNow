"""Tests for osm.classify — defect classification into A, B, AB, C."""

from osm.classify import classify
from osm.config import CLASS_A, CLASS_AB, CLASS_B, CLASS_C, CRITICAL, HIGH, LOW


def _make_way(way_id, name, highway="residential", oneway=None, service=None, geom=None):
    """Build a minimal Overpass way element for testing."""
    tags = {"name": name, "highway": highway}
    if oneway is not None:
        tags["oneway"] = oneway
    if service is not None:
        tags["service"] = service
    if geom is None:
        geom = [
            {"lat": 39.10 + way_id * 0.001, "lon": -84.50},
            {"lat": 39.10 + way_id * 0.001 + 0.0005, "lon": -84.50},
        ]
    return {
        "type": "way",
        "id": way_id,
        "tags": tags,
        "geometry": geom,
        "version": 1,
        "user": "test_user",
    }


def _overpass_response(*ways):
    """Wrap way elements in an Overpass-style response dict."""
    return {"elements": list(ways)}


# ---------------------------------------------------------------------------
# Class A: highway=residential + oneway=yes, unique name
# ---------------------------------------------------------------------------

class TestClassA:

    def test_residential_oneway_is_class_a(self):
        raw = _overpass_response(
            _make_way(1, "Elm Street", highway="residential", oneway="yes"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] == CLASS_A
        assert way["severity"] == CRITICAL

    def test_not_residential_not_class_a(self):
        raw = _overpass_response(
            _make_way(1, "US 50", highway="primary", oneway="yes"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] != CLASS_A

    def test_oneway_missing_not_class_a(self):
        raw = _overpass_response(
            _make_way(1, "Oak Lane", highway="residential"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] != CLASS_A

    def test_tertiary_oneway_is_class_a(self):
        # Bug 3: widen Class-A to non-residential TIGER survivors.
        raw = _overpass_response(
            _make_way(1, "Maple Pkwy", highway="tertiary", oneway="yes"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] == CLASS_A
        assert way["severity"] == CRITICAL

    def test_unclassified_oneway_is_class_a(self):
        raw = _overpass_response(
            _make_way(1, "Back Road", highway="unclassified", oneway="yes"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_A

    def test_oneway_minus_one_is_class_a(self):
        # Bug 7: oneway=-1 (reverse-direction one-way) is also truthy.
        raw = _overpass_response(
            _make_way(1, "Reverse St", highway="residential", oneway="-1"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_A

    def test_oneway_true_is_class_a(self):
        raw = _overpass_response(
            _make_way(1, "True St", highway="residential", oneway="true"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_A


# ---------------------------------------------------------------------------
# Class B: 2+ ways sharing a normalised name
# ---------------------------------------------------------------------------

class TestClassB:

    def test_two_ways_same_name_is_class_b(self):
        raw = _overpass_response(
            _make_way(1, "Vine Street"),
            _make_way(2, "Vine Street"),
        )
        result = classify(raw)
        for w in result["all_ways"]:
            assert w["defect_class"] == CLASS_B
            assert w["severity"] == HIGH

    def test_case_insensitive_grouping(self):
        raw = _overpass_response(
            _make_way(1, "vine street"),
            _make_way(2, "Vine Street"),
        )
        result = classify(raw)
        for w in result["all_ways"]:
            assert w["defect_class"] == CLASS_B

    def test_single_way_not_class_b(self):
        raw = _overpass_response(
            _make_way(1, "Unique Rd"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] != CLASS_B


# ---------------------------------------------------------------------------
# Class AB: both conditions
# ---------------------------------------------------------------------------

class TestClassAB:

    def test_residential_oneway_multi_segment_is_class_ab(self):
        raw = _overpass_response(
            _make_way(1, "Race Street", highway="residential", oneway="yes"),
            _make_way(2, "Race Street", highway="residential"),
        )
        result = classify(raw)
        ab_ways = [w for w in result["all_ways"] if w["defect_class"] == CLASS_AB]
        assert len(ab_ways) == 1
        assert ab_ways[0]["id"] == 1
        assert ab_ways[0]["severity"] == CRITICAL


# ---------------------------------------------------------------------------
# Class C: none of the above
# ---------------------------------------------------------------------------

class TestClassC:

    def test_plain_residential_is_class_c(self):
        raw = _overpass_response(
            _make_way(1, "Quiet Lane", highway="residential"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] == CLASS_C
        assert way["severity"] == LOW

    def test_unnamed_way_is_class_c(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] == CLASS_C


# ---------------------------------------------------------------------------
# summary_stats
# ---------------------------------------------------------------------------

class TestSummaryStats:

    def test_counts_match(self):
        raw = _overpass_response(
            _make_way(1, "Alpha St", highway="residential", oneway="yes"),
            _make_way(2, "Alpha St", highway="residential"),
            _make_way(3, "Beta Ave", highway="residential"),
            _make_way(4, "Gamma Rd", highway="tertiary"),
        )
        result = classify(raw)
        stats = result["summary_stats"]

        assert stats["total"] == 4
        assert stats["residential"] == 3
        # Way 1 is AB, Way 2 is B -> class_a_count includes AB
        assert stats["class_a_count"] == 1    # AB only (class_a includes AB)
        assert stats["class_ab_count"] == 1   # Way 1
        assert stats["class_a_only_count"] == 0
        assert stats["class_b_street_count"] >= 1
        assert stats["by_class"][CLASS_AB] == 1
        assert stats["by_class"][CLASS_B] == 1
        assert stats["by_class"][CLASS_C] == 2



# ---------------------------------------------------------------------------
# Service-subtype filtering: parking aisles, driveways, alleys are
# legitimately oneway and must NOT be flagged Class A.
# ---------------------------------------------------------------------------

class TestServiceSubtypeFiltering:

    def test_parking_aisle_oneway_is_not_class_a(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes",
                      service="parking_aisle"),
        )
        result = classify(raw)
        way = result["all_ways"][0]
        assert way["defect_class"] == CLASS_C
        assert way["severity"] == LOW

    def test_driveway_oneway_is_not_class_a(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes",
                      service="driveway"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_C

    def test_alley_oneway_is_not_class_a(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes",
                      service="alley"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_C

    def test_emergency_access_oneway_is_not_class_a(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes",
                      service="emergency_access"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_C

    def test_unsubtyped_service_oneway_is_still_class_a(self):
        # A `highway=service` way with NO `service=*` value is unclassified
        # service road. Keep flagging these — they may be real defects.
        raw = _overpass_response(
            _make_way(1, "Main Service Rd", highway="service", oneway="yes"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_A

    def test_service_subtype_filter_does_not_affect_residential(self):
        # The exclusion is service-only; residential ways with oneway=yes
        # remain Class A regardless of any other tags.
        raw = _overpass_response(
            _make_way(1, "Elm St", highway="residential", oneway="yes"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_A


# ---------------------------------------------------------------------------
# Unnamed-way labels: classify produces useful descriptors instead of a
# uniform "[Unnamed]" so the inventory UI can tell rows apart at a glance.
# ---------------------------------------------------------------------------

class TestUnnamedLabel:

    def test_unnamed_residential_gets_descriptive_label(self):
        raw = _overpass_response(
            _make_way(1, None, highway="residential"),
        )
        way = classify(raw)["all_ways"][0]
        assert way["name_display"] == "Unnamed residential street"

    def test_unnamed_service_with_subtype_gets_subtype_label(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service", service="parking_aisle"),
        )
        way = classify(raw)["all_ways"][0]
        assert way["name_display"] == "Parking aisle"

    def test_unnamed_service_without_subtype_gets_service_road_label(self):
        raw = _overpass_response(
            _make_way(1, None, highway="service"),
        )
        way = classify(raw)["all_ways"][0]
        assert way["name_display"] == "Service road"

    def test_named_way_preserves_name(self):
        raw = _overpass_response(
            _make_way(1, "Elm Street", highway="residential"),
        )
        way = classify(raw)["all_ways"][0]
        assert way["name_display"] == "Elm Street"

    def test_unnamed_label_never_returns_brackets(self):
        # Regression: the legacy "[Unnamed]" literal is gone. No descriptor
        # should contain square brackets.
        for hw in ("residential", "service", "tertiary", "footway", None):
            raw = _overpass_response(_make_way(1, None, highway=hw or "residential"))
            way = classify(raw)["all_ways"][0]
            assert "[" not in way["name_display"]
            assert "]" not in way["name_display"]


# ---------------------------------------------------------------------------
# include_unnamed_service flag: opt-in escape hatch for exhaustive audits.
# Default behaviour suppresses unnamed service-oneway ways without a service=*
# subtype (interior parking-lot/driveway noise that ViaAlgo can't dispatch
# into anyway).
# ---------------------------------------------------------------------------

class TestIncludeUnnamedServiceFlag:

    def test_unnamed_service_oneway_no_subtype_filtered_by_default(self):
        # Default: noise filtered.
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_C

    def test_unnamed_service_oneway_no_subtype_flagged_when_opt_in(self):
        # Escape hatch: same way, opt-in restores Class A.
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes"),
        )
        result = classify(raw, include_unnamed_service=True)
        assert result["all_ways"][0]["defect_class"] == CLASS_A

    def test_named_service_oneway_still_flagged_in_default_mode(self):
        # Named service ways are not affected by the filter.
        raw = _overpass_response(
            _make_way(1, "Mercy Health Service Drive",
                      highway="service", oneway="yes"),
        )
        result = classify(raw)
        assert result["all_ways"][0]["defect_class"] == CLASS_A

    def test_residential_oneway_unaffected_by_flag(self):
        # The flag is service-only; residential remains Class A regardless.
        raw = _overpass_response(
            _make_way(1, None, highway="residential", oneway="yes"),
        )
        for include in (False, True):
            result = classify(raw, include_unnamed_service=include)
            assert result["all_ways"][0]["defect_class"] == CLASS_A

    def test_subtyped_service_filter_takes_precedence(self):
        # service=parking_aisle is filtered even when include_unnamed_service
        # is True — the subtype filter is a stronger signal of legitimacy.
        raw = _overpass_response(
            _make_way(1, None, highway="service", oneway="yes",
                      service="parking_aisle"),
        )
        result = classify(raw, include_unnamed_service=True)
        assert result["all_ways"][0]["defect_class"] == CLASS_C
