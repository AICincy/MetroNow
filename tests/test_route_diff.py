"""Tests for osm.route_diff — BRouter route-diff harness."""

from __future__ import annotations

import json
import time
from unittest import mock

# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

def _sample_way(way_id: int = 100, *, oneway: str | None = "-1") -> dict:
    """A roughly N-S residential way around Blue Ash coords."""
    tags = {"highway": "residential", "name": "Test Road"}
    if oneway is not None:
        tags["oneway"] = oneway
    return {
        "id": way_id,
        "tags": tags,
        "highway": "residential",
        "name": "Test Road",
        "geometry": [
            {"lat": 39.2300, "lon": -84.3700},
            {"lat": 39.2310, "lon": -84.3700},
            {"lat": 39.2320, "lon": -84.3700},
        ],
    }


def _adjacent_way(way_id: int = 200) -> dict:
    """A drivable way ~80 m east of _sample_way's start, used as origin candidate."""
    return {
        "id": way_id,
        "tags": {"highway": "residential", "name": "Side Street"},
        "highway": "residential",
        "geometry": [
            {"lat": 39.2300, "lon": -84.3690},
            {"lat": 39.2305, "lon": -84.3690},
        ],
    }


def _adjacent_way_far(way_id: int = 201) -> dict:
    """A drivable way ~80 m east of the END of _sample_way."""
    return {
        "id": way_id,
        "tags": {"highway": "residential", "name": "Far Side"},
        "highway": "residential",
        "geometry": [
            {"lat": 39.2320, "lon": -84.3690},
            {"lat": 39.2325, "lon": -84.3690},
        ],
    }


def _isolated_way(way_id: int = 300) -> dict:
    """A way with no candidate neighbours — synth_endpoints must return None."""
    return {
        "id": way_id,
        "tags": {"highway": "residential", "name": "Isolated"},
        "highway": "residential",
        "geometry": [
            {"lat": 41.0000, "lon": -85.0000},
            {"lat": 41.0001, "lon": -85.0000},
        ],
    }


def _brouter_geojson(length_m: float, duration_s: float, cost: float = 100.0) -> dict:
    """Build a sample BRouter GeoJSON FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "creator": "BRouter-1.7.5",
                    "name": "brouter",
                    "track-length": str(length_m),
                    "filtered ascend": "0",
                    "plain-ascend": "0",
                    "total-time": str(duration_s),
                    "total-energy": "0",
                    "cost": str(cost),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-84.3690, 39.2300],
                        [-84.3700, 39.2310],
                        [-84.3700, 39.2320],
                    ],
                },
            }
        ],
    }


class _MockResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload) if payload is not None else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


# ---------------------------------------------------------------------------
# synth_endpoints_around
# ---------------------------------------------------------------------------

class TestSynthEndpoints:

    def test_returns_endpoints_when_neighbours_exist(self):
        from osm.route_diff import synth_endpoints_around
        way = _sample_way()
        ways = [way, _adjacent_way(), _adjacent_way_far()]
        ep = synth_endpoints_around(way, all_ways=ways)
        assert ep is not None
        origin, destination = ep
        # Both endpoints are (lon, lat) tuples on the side-street way (lon=-84.369…).
        assert origin[0] == -84.3690
        assert destination[0] == -84.3690
        # Origin is near the way's start lat (39.2300), destination near end (39.2320).
        assert abs(origin[1] - 39.2300) < 0.001
        assert abs(destination[1] - 39.2320) < 0.001

    def test_returns_none_when_isolated(self):
        from osm.route_diff import synth_endpoints_around
        way = _isolated_way()
        # Provide a neighbour set with no nearby drivable ways — far away.
        far_neighbour = _adjacent_way()
        ep = synth_endpoints_around(way, all_ways=[way, far_neighbour])
        assert ep is None

    def test_fallback_when_no_neighbour_set(self):
        """With ``all_ways=None``, fallback projects endpoints by offset_m."""
        from osm.route_diff import synth_endpoints_around
        way = _sample_way()
        ep = synth_endpoints_around(way, all_ways=None)
        assert ep is not None
        # Origin/destination must differ from the raw geometry coords.
        origin, destination = ep
        assert origin != (way["geometry"][0]["lon"], way["geometry"][0]["lat"])
        assert destination != (way["geometry"][-1]["lon"], way["geometry"][-1]["lat"])


# ---------------------------------------------------------------------------
# fetch_route — mocked HTTP
# ---------------------------------------------------------------------------

class TestFetchRoute:

    def test_parses_brouter_geojson(self, monkeypatch):
        from osm import route_diff as rd_mod
        # Disable polite delay so tests run fast.
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        # Reset module-level last-call timestamp.
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)
        sample = _brouter_geojson(5554.0, 686.0, cost=234.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(sample),
        ):
            res = rd_mod.fetch_route(
                (-84.369, 39.2300), (-84.369, 39.2320),
            )
        assert res is not None
        assert res["length_m"] == 5554.0
        assert res["duration_s"] == 686.0
        assert res["cost"] == 234.0
        assert "geometry" in res

    def test_5xx_returns_none(self, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(None, status_code=500, text="Unreachable"),
        ):
            res = rd_mod.fetch_route(
                (-84.0, 39.0), (-84.0, 39.001),
            )
        assert res is None

    def test_4xx_returns_none(self, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(None, status_code=400, text="Bad request"),
        ):
            res = rd_mod.fetch_route(
                (-84.0, 39.0), (-84.0, 39.001),
            )
        assert res is None

    def test_empty_features_returns_none(self, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)
        empty = {"type": "FeatureCollection", "features": []}
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(empty),
        ):
            res = rd_mod.fetch_route(
                (-84.0, 39.0), (-84.0, 39.001),
            )
        assert res is None

    def test_request_exception_returns_none(self, monkeypatch):
        import requests

        from osm import route_diff as rd_mod
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            side_effect=requests.ConnectionError("offline"),
        ):
            res = rd_mod.fetch_route(
                (-84.0, 39.0), (-84.0, 39.001),
            )
        assert res is None


# ---------------------------------------------------------------------------
# cached_route — TTL & key behaviour
# ---------------------------------------------------------------------------

class TestCachedRoute:

    def test_ttl_honoured(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)

        sample = _brouter_geojson(1000.0, 200.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(sample),
        ) as m:
            first = rd_mod.cached_route(
                (-84.0, 39.0), (-84.0, 39.001), force_refresh=True,
            )
            second = rd_mod.cached_route(
                (-84.0, 39.0), (-84.0, 39.001),
            )
        assert m.call_count == 1
        assert first["length_m"] == 1000.0
        assert second["length_m"] == 1000.0

    def test_ttl_expired_refetches(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_TTL_S", 1)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)

        sample = _brouter_geojson(1000.0, 200.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(sample),
        ) as m:
            rd_mod.cached_route((-84.0, 39.0), (-84.0, 39.001), force_refresh=True)
            # Age cache files past the 1-second TTL.
            import os
            for p in tmp_path.glob("*.json"):
                old = time.time() - 5
                os.utime(p, (old, old))
            rd_mod.cached_route((-84.0, 39.0), (-84.0, 39.001))
        assert m.call_count == 2

    def test_distinct_profiles_hit_distinct_cache_keys(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        monkeypatch.setattr(rd_mod, "_last_call_at", 0.0)

        sample = _brouter_geojson(1000.0, 200.0)
        with mock.patch(
            "osm.route_diff.requests.get",
            return_value=_MockResponse(sample),
        ) as m:
            rd_mod.cached_route(
                (-84.0, 39.0), (-84.0, 39.001),
                profile="car-fast", force_refresh=True,
            )
            rd_mod.cached_route(
                (-84.0, 39.0), (-84.0, 39.001),
                profile="car-vehicle", force_refresh=True,
            )
        assert m.call_count == 2


# ---------------------------------------------------------------------------
# diff_route — decision rule
# ---------------------------------------------------------------------------

def _patched_cached_route(routes_by_call):
    """Build a mock for cached_route that returns the next item per call."""
    queue = list(routes_by_call)

    def _impl(*args, **kwargs):  # noqa: ARG001
        return queue.pop(0)
    return _impl


class TestDiffRoute:

    def test_oneway_minus_one_unreachable_after_perturbation_real(self, tmp_path, monkeypatch):
        """Live route works; perturbed route fails — kind 'real'.

        (This corresponds to the "this way is a critical link, the suspect
        oneway tag would absolutely change routing" branch.)
        """
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        # Live: 1000 m. Perturbed: None (unreachable).
        with mock.patch.object(
            rd_mod, "cached_route",
            side_effect=_patched_cached_route([
                {"length_m": 1000.0, "duration_s": 200.0, "cost": 100.0},
                None,
            ]),
        ):
            way = _sample_way()
            ways = [way, _adjacent_way(), _adjacent_way_far()]
            finding = {"kind": "oneway_minus_one", "id": way["id"], "geometry": way["geometry"]}
            res = rd_mod.diff_route(finding, ways)
        assert res is not None
        assert res["decision"] == "real"
        assert res["after_predicted"]["basis"] == "unreachable"

    def test_oneway_minus_one_unchanged_route_noisy(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        with mock.patch.object(
            rd_mod, "cached_route",
            side_effect=_patched_cached_route([
                {"length_m": 1000.0, "duration_s": 200.0, "cost": 100.0},
                {"length_m": 1010.0, "duration_s": 202.0, "cost": 101.0},  # +1%
            ]),
        ):
            way = _sample_way()
            ways = [way, _adjacent_way(), _adjacent_way_far()]
            finding = {"kind": "oneway_minus_one", "id": way["id"], "geometry": way["geometry"]}
            res = rd_mod.diff_route(finding, ways)
        assert res is not None
        assert res["decision"] == "noisy"
        assert res["delta_pct"] < 3.0
        assert res["after_predicted"]["basis"] == "graph-perturbation"

    def test_oneway_minus_one_meaningful_delta_real(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        with mock.patch.object(
            rd_mod, "cached_route",
            side_effect=_patched_cached_route([
                {"length_m": 1000.0, "duration_s": 200.0, "cost": 100.0},
                {"length_m": 1200.0, "duration_s": 240.0, "cost": 120.0},  # +20%
            ]),
        ):
            way = _sample_way()
            ways = [way, _adjacent_way(), _adjacent_way_far()]
            finding = {"kind": "oneway_minus_one", "id": way["id"], "geometry": way["geometry"]}
            res = rd_mod.diff_route(finding, ways)
        assert res is not None
        assert res["decision"] == "real"
        assert res["delta_pct"] >= 15.0

    def test_inconclusive_when_both_unreachable(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        with mock.patch.object(
            rd_mod, "cached_route",
            side_effect=_patched_cached_route([None, None]),
        ):
            way = _sample_way()
            ways = [way, _adjacent_way(), _adjacent_way_far()]
            finding = {"kind": "oneway_minus_one", "id": way["id"], "geometry": way["geometry"]}
            res = rd_mod.diff_route(finding, ways)
        assert res is not None
        assert res["decision"] == "inconclusive"

    def test_arterial_named_residential_is_untestable(self):
        """Untestable detector kinds return None directly from diff_route."""
        from osm.route_diff import diff_route
        finding = {
            "kind": "arterial_named_residential",
            "id": 999,
            "geometry": [{"lat": 39.23, "lon": -84.37}, {"lat": 39.231, "lon": -84.37}],
        }
        res = diff_route(finding, [])
        assert res is None

    def test_missing_maxspeed_is_untestable(self):
        from osm.route_diff import diff_route
        res = diff_route({"kind": "missing_maxspeed", "id": 5}, [])
        assert res is None

    def test_bus_stop_misplaced_is_untestable(self):
        from osm.route_diff import diff_route
        res = diff_route({"kind": "bus_stop_misplaced", "id": 5}, [])
        assert res is None

    def test_barrier_unqualified_uses_nogo_strategy(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        with mock.patch.object(
            rd_mod, "cached_route",
            side_effect=_patched_cached_route([
                {"length_m": 1000.0, "duration_s": 200.0, "cost": 100.0},
                {"length_m": 1500.0, "duration_s": 300.0, "cost": 150.0},  # +50%
            ]),
        ):
            ways = [_adjacent_way(), _adjacent_way_far()]
            finding = {
                "kind": "barrier_unqualified",
                "id": 42,
                "lat": 39.231,
                "lon": -84.370,
            }
            res = rd_mod.diff_route(finding, ways)
        assert res is not None
        assert res["decision"] == "real"


# ---------------------------------------------------------------------------
# diff_findings + graduate_findings
# ---------------------------------------------------------------------------

class TestBatchAndGraduate:

    def test_diff_findings_skips_untestable(self, tmp_path, monkeypatch):
        from osm import route_diff as rd_mod
        monkeypatch.setattr(rd_mod, "BROUTER_CACHE_DIR", tmp_path)
        monkeypatch.setenv("BROUTER_DELAY_SEC", "0")
        # Don't actually let the testable case touch the network.
        with mock.patch.object(
            rd_mod, "diff_route",
            return_value={"decision": "noisy", "delta_pct": 1.0, "confidence": 0.4},
        ):
            findings = [
                {"kind": "arterial_named_residential", "id": 1},
                {"kind": "oneway_minus_one", "id": 2,
                 "geometry": [{"lat": 39.23, "lon": -84.37},
                              {"lat": 39.231, "lon": -84.37}]},
            ]
            rd_mod.diff_findings(findings, [])
        assert findings[0]["route_diff"] is None
        assert "route_diff_skipped" in findings[0]
        assert findings[1]["route_diff"]["decision"] == "noisy"

    def test_graduate_findings_splits_correctly(self):
        from osm.route_diff import graduate_findings
        findings = [
            # Real & auto-fixable -> graduates.
            {"kind": "oneway_minus_one", "id": 1,
             "route_diff": {"decision": "real", "delta_pct": 30.0}},
            # Real but kind is not in AUTO_FIXABLE_KINDS -> human review.
            {"kind": "arterial_named_residential", "id": 2,
             "route_diff": {"decision": "real", "delta_pct": 30.0}},
            # Noisy -> human review.
            {"kind": "oneway_minus_one", "id": 3,
             "route_diff": {"decision": "noisy", "delta_pct": 1.0}},
            # Untested -> human review.
            {"kind": "barrier_unqualified", "id": 4, "route_diff": None},
            # Real & auto-fixable barrier -> graduates.
            {"kind": "barrier_unqualified", "id": 5,
             "route_diff": {"decision": "real", "delta_pct": 50.0}},
        ]
        graduated, human = graduate_findings(findings)
        assert {f["id"] for f in graduated} == {1, 5}
        assert {f["id"] for f in human} == {2, 3, 4}

    def test_decision_histogram(self):
        from osm.route_diff import decision_histogram
        findings = [
            {"route_diff": {"decision": "real"}},
            {"route_diff": {"decision": "real"}},
            {"route_diff": {"decision": "noisy"}},
            {"route_diff": {"decision": "inconclusive"}},
            {"route_diff": None},
            {"route_diff": None},
        ]
        h = decision_histogram(findings)
        assert h == {"real": 2, "inconclusive": 1, "noisy": 1, "untested": 2}


# ---------------------------------------------------------------------------
# review.proposed_fixes_for_finding integration
# ---------------------------------------------------------------------------

class TestProposedFixesForFinding:

    def test_oneway_minus_one_with_real_decision_emits_fix(self):
        from osm.review import proposed_fixes_for_finding
        finding = {
            "kind": "oneway_minus_one",
            "id": 12345,
            "name": "Bromfield Drive",
            "route_diff": {
                "decision": "real",
                "delta_pct": 22.5,
                "confidence": 0.85,
                "before": {"length_m": 1000.0, "duration_s": 200.0},
                "after_predicted": {"length_m": 1225.0, "duration_s": 245.0,
                                     "basis": "graph-perturbation"},
                "profile": "car-fast",
            },
        }
        fixes = proposed_fixes_for_finding(finding)
        assert len(fixes) == 1
        f = fixes[0]
        assert f["kind"] == "remove_false_oneway_minus_one"
        assert f["element_type"] == "way"
        assert f["element_id"] == 12345
        assert f["changes"] == {"oneway": None}
        assert f["source_evidence"]["brouter_decision"] == "real"
        assert f["source_evidence"]["delta_pct"] == 22.5

    def test_noisy_decision_emits_no_fix(self):
        from osm.review import proposed_fixes_for_finding
        finding = {
            "kind": "oneway_minus_one",
            "id": 1,
            "route_diff": {"decision": "noisy", "delta_pct": 0.5},
        }
        assert proposed_fixes_for_finding(finding) == []

    def test_no_route_diff_emits_no_fix(self):
        from osm.review import proposed_fixes_for_finding
        finding = {"kind": "oneway_minus_one", "id": 1}
        assert proposed_fixes_for_finding(finding) == []

    def test_non_auto_fixable_kind_emits_no_fix(self):
        from osm.review import proposed_fixes_for_finding
        finding = {
            "kind": "missing_maxspeed",
            "id": 1,
            "route_diff": {"decision": "real", "delta_pct": 30.0},
        }
        assert proposed_fixes_for_finding(finding) == []

    def test_barrier_emits_add_access_fix(self):
        from osm.review import proposed_fixes_for_finding
        finding = {
            "kind": "barrier_unqualified",
            "id": 88,
            "name": "gate",
            "route_diff": {
                "decision": "real",
                "delta_pct": 45.0,
                "confidence": 0.9,
            },
        }
        fixes = proposed_fixes_for_finding(finding)
        assert len(fixes) == 1
        assert fixes[0]["kind"] == "add_access_to_barrier"
        assert fixes[0]["element_type"] == "node"
        assert fixes[0]["changes"] == {"access": "yes"}


# ---------------------------------------------------------------------------
# Phase 4b: route-impact for CAGIS-verified mechanical fixes
# ---------------------------------------------------------------------------

class TestRouteImpactForFix:
    """Map CAGIS-verified oneway fix descriptors onto BRouter perturbation."""

    def test_set_oneway_cagis_routes_through_diff_route(self):
        from osm import route_diff as rd_mod
        # Build a fix descriptor matching review.py's set_oneway_cagis shape.
        fix = {
            "kind": "set_oneway_cagis",
            "action": "modify_tag",
            "element_type": "way",
            "element_id": 999,
            "changes": {"oneway": "yes"},
            "confidence": 0.95,
        }
        # Stub the underlying perturbation so we don't hit BRouter.
        with mock.patch.object(rd_mod, "diff_route", autospec=True) as mock_dr:
            mock_dr.return_value = {
                "kind": "route_diff",
                "way_id": 999,
                "decision": "real",
                "delta_pct": 22.0,
                "before": {"length_m": 1000, "duration_s": 200},
                "after_predicted": {
                    "length_m": 1220, "duration_s": 244,
                    "basis": "graph-perturbation",
                },
                "profile": "car-fast",
            }
            out = rd_mod.route_impact_for_fix(fix, all_ways=[])
        assert out is not None
        assert out["fix_kind"] == "set_oneway_cagis"
        assert out["decision"] == "real"
        # diff_route was called with a synthetic finding shaped like
        # an oneway_conflict so it can reuse the existing perturbation.
        synth_arg = mock_dr.call_args[0][0]
        assert synth_arg["kind"] == "oneway_conflict"
        assert synth_arg["id"] == 999
        assert synth_arg["fix_kind"] == "set_oneway_cagis"

    def test_set_maxspeed_cagis_skipped_with_reason(self):
        from osm.route_diff import route_impact_for_fixes
        fixes = [
            {"kind": "set_maxspeed_cagis", "element_id": 1,
             "changes": {"maxspeed": "25 mph"}},
        ]
        route_impact_for_fixes(fixes, [])
        assert fixes[0]["route_impact"] is None
        assert "does not perturb the routing graph" in (
            fixes[0]["route_impact_skipped"]
        )

    def test_remove_oneway_cagis_calls_diff_route(self):
        from osm import route_diff as rd_mod
        fix = {
            "kind": "remove_oneway_cagis",
            "element_id": 1234,
            "changes": {"oneway": None},
        }
        with mock.patch.object(rd_mod, "diff_route", autospec=True) as mock_dr:
            mock_dr.return_value = {
                "decision": "noisy",
                "delta_pct": 1.0,
                "before": {"duration_s": 100},
                "after_predicted": {"duration_s": 101, "basis": "graph-perturbation"},
            }
            out = rd_mod.route_impact_for_fix(fix, [])
        assert out is not None
        assert out["fix_kind"] == "remove_oneway_cagis"

    def test_unknown_fix_kind_returns_none(self):
        from osm.route_diff import route_impact_for_fix
        fix = {"kind": "set_name_cagis", "element_id": 1}
        assert route_impact_for_fix(fix, []) is None

    def test_summarize_route_impact_aggregates(self):
        from osm.route_diff import summarize_route_impact
        fixes = [
            {
                "kind": "set_oneway_cagis", "element_id": 1,
                "route_impact": {
                    "decision": "real", "delta_pct": 25.0,
                    "before": {"duration_s": 100},
                    "after_predicted": {"duration_s": 130},
                },
            },
            {
                "kind": "remove_oneway_cagis", "element_id": 2,
                "route_impact": {
                    "decision": "real", "delta_pct": 18.0,
                    "before": {"duration_s": 200},
                    "after_predicted": {"duration_s": 240},
                },
            },
            {
                "kind": "set_oneway_cagis", "element_id": 3,
                "route_impact": {
                    "decision": "noisy", "delta_pct": 1.0,
                    "before": {"duration_s": 100},
                    "after_predicted": {"duration_s": 100},
                },
            },
            {
                "kind": "set_maxspeed_cagis", "element_id": 4,
                "route_impact": None,
                "route_impact_skipped": "kind 'set_maxspeed_cagis' ...",
            },
        ]
        s = summarize_route_impact(fixes)
        assert s["fixes_total"] == 4
        assert s["fixes_tested"] == 3
        assert s["fixes_skipped"] == 1
        assert s["real"] == 2
        assert s["noisy"] == 1
        assert s["avg_delta_pct_real"] == 21.5
        assert s["max_delta_pct_real"] == 25.0
        assert s["avg_duration_delta_s_real"] == 35.0  # avg(30, 40)

    def test_summarize_route_impact_handles_empty(self):
        from osm.route_diff import summarize_route_impact
        s = summarize_route_impact([])
        assert s["fixes_total"] == 0
        assert s["real"] == 0
        assert s["avg_delta_pct_real"] == 0.0
        assert s["max_delta_pct_real"] == 0.0
