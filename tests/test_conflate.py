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

    def test_geometry_mismatch_parallel_50m_falls_back_to_review(self):
        # Phase 2b fallback: a way 55 m parallel to a same-name CAGIS line
        # is outside the 30 m primary buffer but within the 100 m fallback.
        # Must match via fallback, capped at REVIEW_CONFIDENCE so it shows
        # up in the human-review queue but never auto-submits.
        from osm.conflate import REVIEW_CONFIDENCE, build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 300,
            "name": "Oak Street",
            "geometry": [[39.2005, -84.4000], [39.2005, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m.get("via_fallback") is True
        assert m["confidence"] <= REVIEW_CONFIDENCE
        assert m["hausdorff_m"] > 30.0

    def test_direction_alignment_perpendicular_falls_back_to_review(self):
        # Same fallback logic for a perpendicular crossing: directed
        # Hausdorff is ~50 m (still inside FALLBACK_BUFFER_M); cap holds.
        from osm.conflate import REVIEW_CONFIDENCE, build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 400,
            "name": "Oak Street",
            "geometry": [[39.1995, -84.395], [39.2005, -84.395]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m.get("via_fallback") is True
        assert m["confidence"] <= REVIEW_CONFIDENCE

    def test_fallback_caps_confidence_at_review_even_with_perfect_name(self):
        # A way 60 m parallel with a perfect-name CAGIS feature would
        # otherwise score very high. Fallback must cap at REVIEW_CONFIDENCE.
        from osm.conflate import HIGH_CONFIDENCE, build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 700,
            "name": "Oak Street",
            "geometry": [[39.2006, -84.4000], [39.2006, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m["via_fallback"] is True
        # Critical promotion guardrail: fallback hits never auto-submit.
        assert m["confidence"] < HIGH_CONFIDENCE

    def test_fallback_skipped_beyond_fallback_buffer(self):
        # A way 200 m from any CAGIS line must NOT match — even fallback
        # has a distance gate (FALLBACK_BUFFER_M = 100 m).
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 800,
            "name": "Oak Street",
            "geometry": [[39.2018, -84.4000], [39.2018, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is None

    def test_normal_path_still_marked_via_fallback_false(self):
        # Regression: a perfectly aligned match must still come back with
        # via_fallback=False so downstream code can distinguish.
        from osm.conflate import build_index, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        osm_way = {
            "id": 900,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m["via_fallback"] is False

    def test_directed_hausdorff_matches_osm_fragment_of_long_cagis(self):
        # Phase 2b: this is the F3-fix regression test. CAGIS publishes
        # the WHOLE named-street centerline; OSM has the same street
        # broken into shorter ways at intersections. The symmetric
        # Hausdorff used to reject these by penalising the CAGIS endpoints
        # that fall outside the OSM segment. Directed Hausdorff (OSM→CAGIS
        # only) keeps the match because every OSM point IS on the CAGIS line.
        from osm.conflate import build_index, match_way
        long_cagis = [[-84.42, 39.20], [-84.38, 39.20]]  # ~3.4 km
        idx = build_index([_make_feat(long_cagis, label="OAK ST")])
        # OSM way: short ~430 m fragment in the middle of OAK ST.
        osm_way = {
            "id": 9001,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3950]],
        }
        m = match_way(osm_way, idx)
        assert m is not None, "OSM fragment of long CAGIS centerline must match"
        assert m["confidence"] >= 0.85, (
            f"Expected high confidence for OSM-fragment-of-CAGIS topology, "
            f"got {m['confidence']}"
        )
        assert m["hausdorff_m"] < 1.0, (
            f"Directed haus should be ~0 for an OSM way that lies on CAGIS, "
            f"got {m['hausdorff_m']}"
        )

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


class TestPhase2aDiagnostics:
    """Phase 2a: per-way bucket attribution that does NOT change scoring."""

    def test_matched_high_bucket(self):
        from osm.conflate import (
            BUCKET_MATCHED_HIGH,
            build_index,
            diagnose_way,
        )
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        way = {
            "id": 1,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        d = diagnose_way(way, idx)
        assert d["bucket"] == BUCKET_MATCHED_HIGH
        assert d["confidence"] >= 0.85
        assert d["best_match"] is not None
        assert d["candidates_within_buffer"] >= 1

    def test_matched_review_bucket_for_geometry_drift(self):
        # Same name + perfect direction, but parallel ~20 m offset (within
        # the 30 m buffer). geom_overlap ≈ 0.33 drags confidence into the
        # [0.6, 0.85) review band.
        # 20 m latitude offset ≈ 20/111320 ≈ 0.000180 deg.
        from osm.conflate import (
            BUCKET_MATCHED_REVIEW,
            build_index,
            diagnose_way,
        )
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        way = {
            "id": 2,
            "name": "Oak Street",
            "geometry": [[39.20018, -84.4000], [39.20018, -84.3900]],
        }
        d = diagnose_way(way, idx)
        assert d["bucket"] == BUCKET_MATCHED_REVIEW
        assert 0.6 <= d["confidence"] < 0.85

    def test_f1_no_candidate_far_away(self):
        from osm.conflate import (
            BUCKET_F1_NO_CANDIDATE,
            build_index,
            diagnose_way,
        )
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        # Way ~1 km away → outside even the 30 m STRtree buffer.
        way = {
            "id": 3,
            "name": "Maple Avenue",
            "geometry": [[40.0, -85.0], [40.0001, -85.0]],
        }
        d = diagnose_way(way, idx)
        assert d["bucket"] == BUCKET_F1_NO_CANDIDATE
        assert d["candidates_within_buffer"] == 0

    def test_55m_parallel_classified_correctly(self):
        # 55 m parallel: outside the 30 m primary buffer but within the
        # 100 m FALLBACK_BUFFER_M, so the fallback path classifies this
        # as MATCHED_FALLBACK_REVIEW (capped at REVIEW). Pre-fallback
        # legitimate classifications were F1 or F3; both stay accepted
        # so this test documents the matcher's evolution.
        from osm.conflate import (
            BUCKET_F1_NO_CANDIDATE,
            BUCKET_F3_GEOMETRY_FAIL,
            BUCKET_MATCHED_FALLBACK_REVIEW,
            REVIEW_CONFIDENCE,
            build_index,
            diagnose_way,
        )
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        way = {
            "id": 4,
            "name": "Oak Street",
            "geometry": [[39.2005, -84.4000], [39.2005, -84.3900]],
        }
        d = diagnose_way(way, idx)
        assert d["bucket"] in {
            BUCKET_F1_NO_CANDIDATE,
            BUCKET_F3_GEOMETRY_FAIL,
            BUCKET_MATCHED_FALLBACK_REVIEW,
        }
        if d["bucket"] == BUCKET_MATCHED_FALLBACK_REVIEW:
            assert d["confidence"] is not None
            assert d["confidence"] <= REVIEW_CONFIDENCE

    def test_f2_name_fail_geometry_perfect(self):
        # Geometry is perfect, direction aligned, but name is totally
        # unrelated. This must attribute to F2_NAME_FAIL, not MIXED_LOW.
        from osm.conflate import (
            BUCKET_F2_NAME_FAIL,
            build_index,
            diagnose_way,
        )
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        way = {
            "id": 5,
            "name": "Birch Boulevard",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        d = diagnose_way(way, idx)
        assert d["bucket"] == BUCKET_F2_NAME_FAIL
        assert d["name_similarity"] is not None
        assert d["name_similarity"] < 0.5

    def test_summarize_diagnostics_aggregates_buckets(self):
        from osm.conflate import (
            BUCKET_F1_NO_CANDIDATE,
            BUCKET_F2_NAME_FAIL,
            BUCKET_MATCHED_HIGH,
            summarize_diagnostics,
        )
        rows = [
            {"bucket": BUCKET_MATCHED_HIGH, "way_length_m": 100},
            {"bucket": BUCKET_MATCHED_HIGH, "way_length_m": 80},
            {
                "bucket": BUCKET_F1_NO_CANDIDATE,
                "nearest_distance_m": 45.0,
                "way_length_m": 60,
            },
            {
                "bucket": BUCKET_F2_NAME_FAIL,
                "name_similarity": 0.2,
                "way_length_m": 90,
            },
        ]
        s = summarize_diagnostics(rows)
        assert s["total_ways"] == 4
        assert s["matched_high"] == 2
        assert s["match_rate_pct"] == 50.0
        assert s["auto_submit_rate_pct"] == 50.0
        assert s["buckets"][BUCKET_F1_NO_CANDIDATE] == 1
        assert s["buckets"][BUCKET_F2_NAME_FAIL] == 1
        assert s["f1_nearest_distance_m_stats"]["count"] == 1

    def test_summarize_handles_empty_rows(self):
        from osm.conflate import summarize_diagnostics
        s = summarize_diagnostics([])
        assert s["total_ways"] == 0
        assert s["match_rate_pct"] == 0.0
        assert s["buckets"] == {}
        assert s["f1_nearest_distance_m_stats"] is None

    def test_write_baseline_manifest_round_trips(self, tmp_path):
        import json

        from osm.conflate import (
            BUCKET_MATCHED_HIGH,
            write_baseline_manifest,
        )
        rows = [
            {
                "id": 1,
                "bucket": BUCKET_MATCHED_HIGH,
                "confidence": 0.95,
                "way_length_m": 100,
            },
        ]
        out = tmp_path / "data" / "cagis_baseline_abc1234.json"
        summary = write_baseline_manifest(
            rows, zone_key="blue-ash-montgomery",
            git_sha="abc1234", out_path=out,
        )
        assert out.exists()
        with out.open() as fh:
            payload = json.load(fh)
        assert payload["zone_key"] == "blue-ash-montgomery"
        assert payload["git_sha"] == "abc1234"
        assert payload["summary"] == summary
        assert payload["thresholds"]["BUFFER_M"] == 30.0
        assert len(payload["rows"]) == 1

    def test_polyline_length_helper(self):
        from osm._geometry import polyline_length_m
        # Two-point line at lat 39.2: 0.01 deg lon ≈ 865 m
        length = polyline_length_m([[39.2, -84.4], [39.2, -84.39]])
        assert 850 < length < 880
        # Single-point and empty are zero, never raise.
        assert polyline_length_m([[39.2, -84.4]]) == 0.0
        assert polyline_length_m([]) == 0.0

    def test_diff_baselines_basic_bucket_shifts(self):
        from osm.conflate import diff_baselines
        a = {
            "zone_key": "blue-ash-montgomery",
            "git_sha": "old123",
            "summary": {
                "total_ways": 1000,
                "match_rate_pct": 10.0,
                "auto_submit_rate_pct": 8.0,
                "buckets": {
                    "MATCHED_HIGH": 80,
                    "MATCHED_REVIEW": 20,
                    "F3_GEOMETRY_FAIL": 700,
                    "F1_NO_CANDIDATE": 200,
                },
            },
        }
        b = {
            "zone_key": "blue-ash-montgomery",
            "git_sha": "new456",
            "summary": {
                "total_ways": 1000,
                "match_rate_pct": 12.0,
                "auto_submit_rate_pct": 10.0,
                "buckets": {
                    "MATCHED_HIGH": 100,        # +20 (good)
                    "MATCHED_REVIEW": 20,       # unchanged
                    "F3_GEOMETRY_FAIL": 680,    # -20 (came from here)
                    "F1_NO_CANDIDATE": 200,
                },
            },
        }
        d = diff_baselines(a, b)
        assert d["git_sha_a"] == "old123"
        assert d["git_sha_b"] == "new456"
        assert d["buckets"]["MATCHED_HIGH"]["delta"] == 20
        assert d["buckets"]["F3_GEOMETRY_FAIL"]["delta"] == -20
        assert d["alerts"] == []   # clean — HIGH grew from F3, REVIEW stable

    def test_diff_baselines_flags_fragile_graduation(self):
        # MATCHED_REVIEW contracted to feed MATCHED_HIGH growth — the
        # asymmetric promotion criterion violation.
        from osm.conflate import diff_baselines
        a = {"summary": {"buckets": {
            "MATCHED_HIGH": 100, "MATCHED_REVIEW": 50, "F3_GEOMETRY_FAIL": 500,
        }, "total_ways": 700}}
        b = {"summary": {"buckets": {
            "MATCHED_HIGH": 130, "MATCHED_REVIEW": 20, "F3_GEOMETRY_FAIL": 500,
        }, "total_ways": 700}}
        d = diff_baselines(a, b)
        assert any("REGRESSION" in alert for alert in d["alerts"])

    def test_diff_baselines_flags_total_ways_drift(self):
        from osm.conflate import diff_baselines
        a = {"summary": {"buckets": {"MATCHED_HIGH": 100}, "total_ways": 1000}}
        b = {"summary": {"buckets": {"MATCHED_HIGH": 100}, "total_ways": 1500}}
        d = diff_baselines(a, b)
        assert any("total_ways" in alert for alert in d["alerts"])

    def test_load_baseline_manifest_rejects_malformed(self, tmp_path):
        import json as _json
        from osm.conflate import load_baseline_manifest
        # Missing summary.buckets
        bad = tmp_path / "bad.json"
        bad.write_text(_json.dumps({"summary": {}}))
        try:
            load_baseline_manifest(bad)
        except ValueError as exc:
            assert "summary.buckets" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_newest_two_manifests_picks_by_mtime(self, tmp_path):
        import time
        from osm.conflate import newest_two_manifests
        a = tmp_path / "cagis_baseline_aaa111.json"
        b = tmp_path / "cagis_baseline_bbb222.json"
        c = tmp_path / "cagis_baseline_ccc333.json"
        a.write_text("{}")
        time.sleep(0.01)
        b.write_text("{}")
        time.sleep(0.01)
        c.write_text("{}")
        pair = newest_two_manifests(tmp_path)
        assert pair is not None
        older, newer = pair
        assert older.name == "cagis_baseline_bbb222.json"
        assert newer.name == "cagis_baseline_ccc333.json"

    def test_newest_two_manifests_returns_none_when_too_few(self, tmp_path):
        from osm.conflate import newest_two_manifests
        assert newest_two_manifests(tmp_path) is None
        (tmp_path / "cagis_baseline_only_one.json").write_text("{}")
        assert newest_two_manifests(tmp_path) is None

    def test_diagnose_does_not_mutate_match_output(self):
        # Phase 2a guarantee: running diagnose_way must NOT change what
        # match_way returns for the same input. This is the regression
        # gate for the matcher being read-only.
        from osm.conflate import build_index, diagnose_way, match_way
        idx = build_index([_make_feat(OAK_COORDS, label="OAK ST")])
        way = {
            "id": 6,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        before = match_way(way, idx)
        diagnose_way(way, idx)
        after = match_way(way, idx)
        assert before == after


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
