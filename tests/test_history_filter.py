"""Tests for osm.history_filter — review status assignment and helper predicates."""

from osm.history_filter import (
    ReviewStatus,
    _is_import_user,
    _only_tiger_tags_changed,
    analyse_way_history,
)


# ---------------------------------------------------------------------------
# analyse_way_history — Tier 1 (metadata-only) paths
# ---------------------------------------------------------------------------

class TestAnalyseWayHistory:

    def test_version_1_is_unreviewed(self):
        way = {"id": 100, "version": 1, "user": "TIGERcnl"}
        result = analyse_way_history(way)
        assert result["review_status"] == ReviewStatus.UNREVIEWED
        assert result["review_confidence"] >= 0.9

    def test_version_3_human_user_is_likely_reviewed(self):
        way = {"id": 200, "version": 3, "user": "local_mapper"}
        result = analyse_way_history(way)
        assert result["review_status"] == ReviewStatus.LIKELY_REVIEWED
        assert "local_mapper" in result["review_reason"]

    def test_version_2_human_user_is_likely_reviewed(self):
        way = {"id": 300, "version": 2, "user": "jane_doe"}
        result = analyse_way_history(way)
        assert result["review_status"] == ReviewStatus.LIKELY_REVIEWED

    def test_confidence_increases_with_version(self):
        way_v2 = {"id": 1, "version": 2, "user": "mapper_a"}
        way_v10 = {"id": 2, "version": 10, "user": "mapper_b"}
        r2 = analyse_way_history(way_v2)
        r10 = analyse_way_history(way_v10)
        assert r10["review_confidence"] > r2["review_confidence"]

    def test_confidence_caps_at_085(self):
        way = {"id": 3, "version": 50, "user": "mapper_c"}
        result = analyse_way_history(way)
        assert result["review_confidence"] <= 0.85


# ---------------------------------------------------------------------------
# _is_import_user
# ---------------------------------------------------------------------------

class TestIsImportUser:

    def test_known_import_users(self):
        assert _is_import_user("TIGERcnl") is True
        assert _is_import_user("bot-mode") is True
        assert _is_import_user("DaveHansenTiger") is True
        assert _is_import_user("woodpeck_fixbot") is True

    def test_bot_prefix_match(self):
        assert _is_import_user("bot-something") is True
        assert _is_import_user("import_roads") is True
        assert _is_import_user("fix_geometry") is True
        assert _is_import_user("cleanup_tiger") is True

    def test_bot_prefix_case_insensitive(self):
        assert _is_import_user("BOT-upper") is True
        assert _is_import_user("Import_Test") is True

    def test_human_users(self):
        assert _is_import_user("local_mapper") is False
        assert _is_import_user("jane_doe") is False
        assert _is_import_user("JohnSmith") is False

    def test_none_and_empty(self):
        assert _is_import_user(None) is False
        assert _is_import_user("") is False


# ---------------------------------------------------------------------------
# _only_tiger_tags_changed
# ---------------------------------------------------------------------------

class TestOnlyTigerTagsChanged:

    def test_only_tiger_tags_differ(self):
        prev = {"tiger:cfcc": "A41", "name": "Main St", "highway": "residential"}
        curr = {"tiger:cfcc": "A42", "name": "Main St", "highway": "residential"}
        assert _only_tiger_tags_changed(prev, curr) is True

    def test_source_tag_is_tiger(self):
        prev = {"source": "tiger/line", "name": "Elm St"}
        curr = {"source": "survey", "name": "Elm St"}
        assert _only_tiger_tags_changed(prev, curr) is True

    def test_source_name_is_tiger(self):
        prev = {"source:name": "TIGER 2008", "highway": "residential"}
        curr = {"source:name": "TIGER 2020", "highway": "residential"}
        assert _only_tiger_tags_changed(prev, curr) is True

    def test_non_tiger_tag_changed(self):
        prev = {"name": "Main St", "highway": "residential"}
        curr = {"name": "Main St", "highway": "tertiary"}
        assert _only_tiger_tags_changed(prev, curr) is False

    def test_added_non_tiger_tag(self):
        prev = {"name": "Oak Ave"}
        curr = {"name": "Oak Ave", "surface": "asphalt"}
        assert _only_tiger_tags_changed(prev, curr) is False

    def test_identical_tags(self):
        tags = {"name": "Vine St", "highway": "residential", "tiger:cfcc": "A41"}
        assert _only_tiger_tags_changed(tags, tags) is True

    def test_empty_tags(self):
        assert _only_tiger_tags_changed({}, {}) is True
