"""Tests for osm.motis — MOTIS routing-engine client (prototype).

All tests use tmp_path-isolated cache dirs and unittest.mock for the
network. No live MOTIS instance is required.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest


@pytest.fixture
def isolated_motis(tmp_path, monkeypatch):
    from osm import motis as m

    monkeypatch.setattr(m, "MOTIS_CACHE_DIR", tmp_path / "motis_cache")
    monkeypatch.delenv("MOTIS_BASE", raising=False)
    return m


def _stub_response(status_code: int, payload: dict | None = None,
                   text: str | None = None):
    class _R:
        def __init__(self):
            self.status_code = status_code
            self._payload = payload
            self.text = text or (json.dumps(payload) if payload else "")

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload
    return _R()


# ---------------------------------------------------------------------------
# Polyline decoding
# ---------------------------------------------------------------------------

class TestDecodePolyline:

    def test_empty_string_returns_empty(self, isolated_motis):
        assert isolated_motis.decode_polyline("") == []

    def test_decodes_simple_two_point_polyline_precision_5(self, isolated_motis):
        # Single point: lat=38.5, lon=-120.2 at precision=5 encodes as "_p~iF~ps|U"
        # (canonical example from Google's polyline algorithm reference).
        out = isolated_motis.decode_polyline("_p~iF~ps|U", precision=5)
        assert len(out) == 1
        lon, lat = out[0]
        assert abs(lat - 38.5) < 1e-5
        assert abs(lon - (-120.2)) < 1e-5

    def test_precision_6_is_10x_finer_than_precision_5(self, isolated_motis):
        # Same encoded string decoded at p=5 vs p=6 should differ by a
        # factor of 10 in both lat and lon. This pins down the precision
        # divisor without needing a hand-encoded p=6 fixture.
        s = "_p~iF~ps|U"
        p5 = isolated_motis.decode_polyline(s, precision=5)
        p6 = isolated_motis.decode_polyline(s, precision=6)
        assert len(p5) == 1 and len(p6) == 1
        lon5, lat5 = p5[0]
        lon6, lat6 = p6[0]
        assert abs(lat5 / lat6 - 10) < 1e-9
        assert abs(lon5 / lon6 - 10) < 1e-9


# ---------------------------------------------------------------------------
# /api/v5/plan happy path
# ---------------------------------------------------------------------------

SAMPLE_PLAN_RESPONSE = {
    "itineraries": [
        {
            "duration": 1234,
            "startTime": "2026-05-08T12:00:00Z",
            "endTime": "2026-05-08T12:20:34Z",
            "legs": [
                {
                    "distance": 800.0,
                    "legGeometry": {
                        "points": "_uvkjAvqgytL",
                        "precision": 6,
                    },
                },
                {
                    "distance": 200.0,
                    "legGeometry": {
                        "points": "_uvkjAvqgytL",
                        "precision": 6,
                    },
                },
            ],
        }
    ]
}


class TestFetchRouteHappyPath:

    def test_returns_pipeline_shape(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ):
            out = m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is not None
        assert out["length_m"] == 1000.0
        assert out["duration_s"] == 1234
        assert out["cost"] == 1234
        assert len(out["geometry"]) == 2  # two legs, one point each

    def test_origin_destination_flipped_to_lat_lon_at_wire(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ) as mreq:
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        params = mreq.call_args.kwargs["params"]
        # MOTIS wants "lat,lon"
        assert params["fromPlace"] == "39.2,-84.4"
        assert params["toPlace"] == "39.3,-84.5"

    def test_transit_mode_routes_via_transitModes(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ) as mreq:
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), mode="TRANSIT")
        params = mreq.call_args.kwargs["params"]
        assert params["transitModes"] == "TRANSIT"
        assert params["directModes"] == "WALK"

    def test_walk_mode_routes_via_directModes(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ) as mreq:
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), mode="WALK")
        params = mreq.call_args.kwargs["params"]
        assert params["directModes"] == "WALK"
        assert "transitModes" not in params


# ---------------------------------------------------------------------------
# Fail-open behaviours
# ---------------------------------------------------------------------------

class TestFailOpen:

    def test_connection_refused_returns_none(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            side_effect=m.requests.RequestException("connection refused"),
        ):
            out = m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is None

    def test_500_returns_none(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(500, text="internal error"),
        ):
            out = m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is None

    def test_400_returns_none(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(400, text="bad request"),
        ):
            out = m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is None

    def test_non_json_returns_none(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, text="not json"),
        ):
            out = m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is None

    def test_empty_itineraries_returns_none(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, {"itineraries": []}),
        ):
            out = m.fetch_route((-84.4, 39.2), (-84.5, 39.3))
        assert out is None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class TestCache:

    def test_second_call_with_same_args_skips_network(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ) as mreq:
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), mode="WALK")
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), mode="WALK")
        assert mreq.call_count == 1

    def test_use_cache_false_always_fetches(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ) as mreq:
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), use_cache=False)
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), use_cache=False)
        assert mreq.call_count == 2

    def test_different_modes_dont_share_cache(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, SAMPLE_PLAN_RESPONSE),
        ) as mreq:
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), mode="WALK")
            m.fetch_route((-84.4, 39.2), (-84.5, 39.3), mode="TRANSIT")
        assert mreq.call_count == 2


# ---------------------------------------------------------------------------
# is_available probe
# ---------------------------------------------------------------------------

class TestIsAvailable:

    def test_responds_2xx_means_available(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, {"itineraries": []}),
        ):
            assert m.is_available() is True

    def test_connection_refused_means_unavailable(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            side_effect=m.requests.RequestException("refused"),
        ):
            assert m.is_available() is False

    def test_5xx_means_unavailable(self, isolated_motis):
        m = isolated_motis
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(503, text="upstream"),
        ):
            assert m.is_available() is False

    def test_uses_motis_base_env_var(self, isolated_motis, monkeypatch):
        m = isolated_motis
        monkeypatch.setenv("MOTIS_BASE", "http://my-motis:9000")
        with mock.patch.object(
            m.requests, "get", autospec=True,
            return_value=_stub_response(200, {}),
        ) as mreq:
            m.is_available()
        url = mreq.call_args.args[0]
        assert url.startswith("http://my-motis:9000")
