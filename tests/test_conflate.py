"""Tests for osm.conflate — CAGIS centerline matching."""

from __future__ import annotations

import sys
from unittest import mock

import pytest


def _make_feat(
    coords: list[list[float]],
    *,
    objectid: int = 1,
    label: str = "OAK ST",
    trvl_dir: int = 0,
    cagis_class: int = 5,
    speed: int = 25,
) -> dict:
    """Helper: build a CAGIS-shaped GeoJSON feature."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "OBJECTID": objectid,
            "STRLABEL": label,
            "TRVL_DIR": trvl_dir,
            "CLASS": cagis_class,
            "SPEEDLIMIT": speed,
        },
    }


# Two parallel east-west lines along lat 39.20:
#   "OAK ST"   from (-84.40, 39.20) to (-84.39, 39.20)  (~865 m long)
#   "ELM AVE"  from (-84.40, 39.205) to (-84.39, 39.205) (~50 m north of OAK)
OAK_COORDS = [[-84.40, 39.20], [-84.39, 39.20]]
ELM_COORDS = [[-84.40, 39.205], [-84.39, 39.205]]


class TestConflate:

    def test_match_aligned_same_name_high_confidence(self):
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 100,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m["cagis_id"] == 1
        assert m["cagis_name"] == "OAK ST"
        assert m["cagis_oneway"] == "no"
        assert m["cagis_speed_limit"] == 25
        assert m["cagis_functional_class"] == "local"
        assert m["confidence"] >= 0.8
        assert m["hausdorff_m"] < 1.0

    def test_name_mismatch_lowers_confidence(self):
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 200,
            "name": "Birch Boulevard",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        m = match_way(osm_way, idx)
        # geometry overlaps perfectly → still gets a candidate, but
        # confidence should drop because name_similarity is low.
        assert m is not None
        assert m["name_similarity"] < 0.4
        assert m["confidence"] < 0.7
        assert m["name_match"] is False

    def test_geometry_mismatch_parallel_50m_no_match(self):
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        # Way running parallel ~55 m north (outside the 30 m buffer).
        osm_way = {
            "id": 300,
            "name": "Oak Street",
            "geometry": [[39.2005, -84.4000], [39.2005, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is None

    def test_direction_alignment_perpendicular_lowers_confidence(self):
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        # Way running perpendicular but crossing the centerline (so within
        # the 30 m buffer at the crossing point); however, endpoint distances
        # of a north-south way to the east-west centerline should put the
        # Hausdorff over the buffer.
        osm_way = {
            "id": 400,
            "name": "Oak Street",
            "geometry": [[39.1995, -84.395], [39.2005, -84.395]],
        }
        m = match_way(osm_way, idx)
        # Hausdorff between perpendicular short crossings ≈ 55 m → no match.
        assert m is None

    def test_opposite_direction_still_aligns(self):
        # Direction is undirected (we use abs(cos)) so reversing endpoints
        # should still produce a high-confidence match.
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 500,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.3900], [39.2000, -84.4000]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m["confidence"] >= 0.8

    def test_oneway_decoded(self):
        from osm.conflate import _decode_oneway
        assert _decode_oneway(0) == "no"
        assert _decode_oneway(1) == "yes"
        assert _decode_oneway(-1) == "-1"
        assert _decode_oneway(None) == "no"
        assert _decode_oneway("garbage") == "no"

    def test_conflate_attaches_match_to_every_way(self):
        from osm.conflate import build_index, conflate
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        ways = [
            {
                "id": 1,
                "name": "Oak Street",
                "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
            },
            {
                "id": 2,
                "name": "Far Away",
                # Outside the bbox of CAGIS data → no match.
                "geometry": [[40.0, -85.0], [40.0001, -85.0]],
            },
        ]
        conflate(ways, idx)
        assert ways[0]["cagis_match"] is not None
        assert ways[1]["cagis_match"] is None

    def test_build_index_returns_empty_for_no_features(self):
        from osm.conflate import build_index
        idx = build_index([])
        assert len(idx) == 0
        # Querying empty index should not crash.
        assert idx.match([[39.2, -84.4], [39.2, -84.39]], "Oak Street") is None

    def test_cagis_class_codes_map_to_labels(self):
        from osm.conflate import CAGIS_FUNCTIONAL_CLASS
        assert CAGIS_FUNCTIONAL_CLASS[1] == "interstate"
        assert CAGIS_FUNCTIONAL_CLASS[2] == "arterial"
        assert CAGIS_FUNCTIONAL_CLASS[5] == "local"
        assert CAGIS_FUNCTIONAL_CLASS[6] == "ramp"

    def test_feature_url_format(self):
        from osm.conflate import feature_url
        url = feature_url(12345)
        assert url.endswith("/26/12345")
        assert "FeatureServer" in url


class TestShapelyDegradation:
    """When shapely isn't importable the whole conflation layer must skip
    cleanly without crashing the existing pipeline."""

    def test_module_reload_without_shapely(self):
        """Force-import osm.conflate with shapely shadowed → SHAPELY_AVAILABLE
        becomes False and build_index/match_way return empty/None."""
        import importlib
        # Stash any current bindings so this test is self-contained.
        saved_modules = {
            k: sys.modules.get(k)
            for k in (
                "osm.conflate", "shapely", "shapely.geometry", "shapely.strtree",
            )
        }
        try:
            # Drop osm.conflate so it picks up the new shapely state.
            sys.modules.pop("osm.conflate", None)
            # Block shapely sub-imports.
            sys.modules["shapely"] = None  # type: ignore[assignment]
            sys.modules["shapely.geometry"] = None  # type: ignore[assignment]
            sys.modules["shapely.strtree"] = None  # type: ignore[assignment]

            with mock.patch.dict(sys.modules, {
                "shapely": None,
                "shapely.geometry": None,
                "shapely.strtree": None,
            }):
                # The dict mutation makes import * raise ImportError; the
                # module's try/except should swallow it and set
                # SHAPELY_AVAILABLE = False.
                conflate_mod = importlib.import_module("osm.conflate")
                # Re-execute to ensure the import failure path was taken even
                # if the module had been previously imported with shapely
                # available.
                conflate_mod = importlib.reload(conflate_mod)

                assert conflate_mod.SHAPELY_AVAILABLE is False
                idx = conflate_mod.build_index([_make_feat(OAK_COORDS)])
                assert len(idx) == 0
                assert idx.available is False

                osm_way = {
                    "id": 99,
                    "name": "Oak Street",
                    "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
                }
                assert conflate_mod.match_way(osm_way, idx) is None

                ways = [osm_way]
                conflate_mod.conflate(ways, idx)
                assert ways[0]["cagis_match"] is None
        finally:
            # Restore the real module state for subsequent tests.
            for k, v in saved_modules.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            # Force a clean reimport of osm.conflate with real shapely.
            sys.modules.pop("osm.conflate", None)


class TestReviewCagisIntegration:
    """End-to-end: a way + its CAGIS match should produce evidence-backed
    fixes via osm.review.proposed_fixes_for_way."""

    def test_class_a_with_high_confidence_cagis_no_oneway(self):
        from osm.review import proposed_fixes_for_way
        way = {
            "id": 1000,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "yes",
            "name": "Oak Street",
            "name_display": "Oak Street",
            "cagis_match": {
                "cagis_id": 42,
                "cagis_name": "OAK ST",
                "cagis_oneway": "no",
                "confidence": 0.92,
                "hausdorff_m": 1.5,
                "name_similarity": 0.95,
            },
        }
        fixes = proposed_fixes_for_way(way)
        assert len(fixes) >= 1
        oneway_fix = next(f for f in fixes if f["kind"] == "remove_false_oneway")
        assert oneway_fix["action"] == "remove_tag"
        assert oneway_fix["requires_human_review"] is False
        assert oneway_fix["source_evidence"]["cagis_id"] == 42
        # Description carries CAGIS attribution.
        assert "CAGIS" in oneway_fix["description"]

    def test_low_confidence_marks_human_review(self):
        from osm.review import proposed_fixes_for_way
        way = {
            "id": 1001,
            "defect_class": "C",
            "highway": "residential",
            "oneway": None,
            "name": "Maple Lane",
            "name_display": "Maple Lane",
            "maxspeed": None,
            "cagis_match": {
                "cagis_id": 99,
                "cagis_name": "MAPLE LN",
                "cagis_oneway": "no",
                "cagis_speed_limit": 25,
                "confidence": 0.65,
                "hausdorff_m": 8.0,
                "name_similarity": 0.6,
            },
        }
        fixes = proposed_fixes_for_way(way)
        # A maxspeed fix should be proposed but flagged for review.
        speed_fixes = [f for f in fixes if f["kind"] == "set_maxspeed_cagis"]
        assert len(speed_fixes) == 1
        assert speed_fixes[0]["requires_human_review"] is True
        assert speed_fixes[0]["changes"] == {"maxspeed": "25 mph"}

    def test_legacy_proposed_fix_unchanged_for_class_a(self):
        # Backwards-compat: proposed_fix() must keep returning a single dict
        # for legacy Class A defects without cagis_match.
        from osm.review import proposed_fix
        way = {
            "id": 1002,
            "defect_class": "A",
            "highway": "residential",
            "oneway": "yes",
            "name_display": "Pine Street",
        }
        fix = proposed_fix(way)
        assert fix is not None
        assert fix["action"] == "remove_tag"
        assert fix["tag"] == "oneway"
