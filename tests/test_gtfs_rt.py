"""Tests for osm.gtfs_rt — SORTA direct GTFS-Realtime feed parsing.

Fail-open paths (missing gtfs-realtime-bindings, network errors, unknown
feeds, malformed bytes) are tested without the protobuf package; the
parsing tests build synthetic FeedMessage payloads and so skip cleanly
when gtfs-realtime-bindings isn't installed (it's a hard dep, so CI runs
them — only a bare dev checkout without the package would skip).
"""

from __future__ import annotations

import time
from unittest import mock

import pytest

from osm import gtfs_rt as g


@pytest.fixture
def isolated_rt(tmp_path, monkeypatch):
    """Redirect the GTFS-RT on-disk cache to tmp_path."""
    monkeypatch.setattr(g, "CACHE_DIR", tmp_path / "gtfs_rt_cache")
    return g


# ---------------------------------------------------------------------------
# Fail-open paths (no protobuf package needed)
# ---------------------------------------------------------------------------

class TestFailOpen:

    def test_missing_bindings_returns_empty(self, isolated_rt):
        with mock.patch.object(g, "_import_pb", return_value=None):
            assert g.vehicle_positions() == []
            assert g.trip_updates() == []
            assert g.fetch("vehicles") == []
            assert g.fetch("trips") == []

    def test_unknown_feed_name_returns_empty(self, isolated_rt):
        assert g.fetch("nope") == []
        assert g._fetch_raw("nope") is None

    def test_network_error_no_cache_returns_none(self, isolated_rt):
        import requests
        with mock.patch.object(
            g.requests, "get", autospec=True,
            side_effect=requests.RequestException("offline"),
        ):
            assert g._fetch_raw("vehicles") is None

    def test_network_error_falls_back_to_stale_cache(self, isolated_rt):
        import requests
        isolated_rt.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached = isolated_rt.CACHE_DIR / "vehicles.pb"
        cached.write_bytes(b"stale-bytes")
        # Make the cache "stale" so the TTL fast-path is skipped.
        old = time.time() - (g.CACHE_TTL_S + 60)
        import os
        os.utime(cached, (old, old))
        with mock.patch.object(
            g.requests, "get", autospec=True,
            side_effect=requests.RequestException("offline"),
        ):
            assert g._fetch_raw("vehicles") == b"stale-bytes"

    def test_http_error_records_feed_error(self, isolated_rt, monkeypatch):
        import requests
        recorded = []
        from osm import feed_errors
        monkeypatch.setattr(
            feed_errors, "record",
            lambda feed, reason, detail="": recorded.append((feed, reason)),
        )
        with mock.patch.object(
            g.requests, "get", autospec=True,
            side_effect=requests.RequestException("boom"),
        ):
            g._fetch_raw("vehicles")
        assert recorded and recorded[0][0] == "gtfs_rt"

    def test_fresh_cache_short_circuits_network(self, isolated_rt):
        isolated_rt.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (isolated_rt.CACHE_DIR / "vehicles.pb").write_bytes(b"fresh")
        with mock.patch.object(g.requests, "get", autospec=True) as m:
            assert g._fetch_raw("vehicles") == b"fresh"
            m.assert_not_called()

    def test_force_refresh_bypasses_fresh_cache(self, isolated_rt):
        import requests
        isolated_rt.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (isolated_rt.CACHE_DIR / "vehicles.pb").write_bytes(b"old")
        with mock.patch.object(
            g.requests, "get", autospec=True,
            side_effect=requests.RequestException("offline"),
        ):
            # force_refresh skips the fresh-cache fast-path; the failed
            # fetch then falls back to the same cached bytes.
            assert g._fetch_raw("vehicles", force_refresh=True) == b"old"


# ---------------------------------------------------------------------------
# Parsing (needs gtfs-realtime-bindings; skips cleanly without it)
# ---------------------------------------------------------------------------

@pytest.fixture
def pb():
    return pytest.importorskip("google.transit.gtfs_realtime_pb2")


def _feed_header(pb_mod):
    msg = pb_mod.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    return msg


class TestVehiclePositionsParsing:

    def test_parses_a_vehicle_entity(self, isolated_rt, pb):
        msg = _feed_header(pb)
        ent = msg.entity.add()
        ent.id = "v1"
        v = ent.vehicle
        v.vehicle.id = "BUS-204"
        v.trip.trip_id = "T1"
        v.trip.route_id = "4"
        v.position.latitude = 39.232
        v.position.longitude = -84.378
        v.position.bearing = 270.0
        v.timestamp = 1_700_000_000
        v.current_status = pb.VehiclePosition.IN_TRANSIT_TO
        v.stop_id = "S9"
        raw = msg.SerializeToString()
        with mock.patch.object(g, "_fetch_raw", return_value=raw):
            out = g.vehicle_positions()
        assert len(out) == 1
        r = out[0]
        assert r["vehicle_id"] == "BUS-204"
        assert r["trip_id"] == "T1" and r["route_id"] == "4"
        # GTFS-RT Position lat/lon/bearing are 32-bit `float`, so values
        # round-trip to ~1e-6 precision — don't assert tighter than that.
        assert abs(r["lat"] - 39.232) < 1e-4 and abs(r["lon"] + 84.378) < 1e-4
        assert abs(r["bearing"] - 270.0) < 1e-4
        assert r["timestamp"] == 1_700_000_000
        assert r["current_status"] == int(pb.VehiclePosition.IN_TRANSIT_TO)
        assert r["stop_id"] == "S9"

    def test_skips_non_vehicle_entities(self, isolated_rt, pb):
        msg = _feed_header(pb)
        ent = msg.entity.add()
        ent.id = "a1"
        ent.alert.header_text.translation.add().text = "Detour"
        with mock.patch.object(g, "_fetch_raw", return_value=msg.SerializeToString()):
            assert g.vehicle_positions() == []

    def test_absent_optionals_become_none(self, isolated_rt, pb):
        msg = _feed_header(pb)
        ent = msg.entity.add()
        ent.id = "v2"
        ent.vehicle.position.latitude = 39.1
        ent.vehicle.position.longitude = -84.5
        with mock.patch.object(g, "_fetch_raw", return_value=msg.SerializeToString()):
            r = g.vehicle_positions()[0]
        assert r["bearing"] is None and r["timestamp"] is None
        assert r["current_status"] is None and r["stop_id"] is None


class TestTripUpdatesParsing:

    def test_parses_a_trip_update(self, isolated_rt, pb):
        msg = _feed_header(pb)
        ent = msg.entity.add()
        ent.id = "tu1"
        tu = ent.trip_update
        tu.trip.trip_id = "T7"
        tu.trip.route_id = "67"
        tu.vehicle.id = "BUS-9"
        tu.timestamp = 1_700_000_500
        s1 = tu.stop_time_update.add()
        s1.stop_id = "S1"
        s1.stop_sequence = 3
        s1.arrival.time = 1_700_000_900
        s1.arrival.delay = 120
        s2 = tu.stop_time_update.add()
        s2.stop_id = "S2"
        s2.departure.delay = -30
        with mock.patch.object(g, "_fetch_raw", return_value=msg.SerializeToString()):
            out = g.trip_updates()
        assert len(out) == 1
        r = out[0]
        assert r["trip_id"] == "T7" and r["route_id"] == "67"
        assert r["vehicle_id"] == "BUS-9" and r["timestamp"] == 1_700_000_500
        assert len(r["stop_time_updates"]) == 2
        u1 = r["stop_time_updates"][0]
        assert u1["stop_id"] == "S1" and u1["stop_sequence"] == 3
        assert u1["arrival_time"] == 1_700_000_900 and u1["arrival_delay"] == 120
        assert u1["departure_time"] is None and u1["departure_delay"] is None
        u2 = r["stop_time_updates"][1]
        assert u2["stop_id"] == "S2" and u2["departure_delay"] == -30
        assert u2["arrival_time"] is None and u2["stop_sequence"] is None

    def test_skips_non_trip_update_entities(self, isolated_rt, pb):
        msg = _feed_header(pb)
        ent = msg.entity.add()
        ent.id = "v9"
        ent.vehicle.position.latitude = 39.0
        ent.vehicle.position.longitude = -84.0
        with mock.patch.object(g, "_fetch_raw", return_value=msg.SerializeToString()):
            assert g.trip_updates() == []


class TestParseErrors:

    def test_malformed_bytes_return_empty(self, isolated_rt, pb):
        with mock.patch.object(g, "_fetch_raw", return_value=b"\xff\xff not protobuf"):
            assert g.vehicle_positions() == []
            assert g.trip_updates() == []

    def test_fetch_dispatch_and_force_refresh(self, isolated_rt, pb):
        msg = _feed_header(pb)
        ent = msg.entity.add()
        ent.id = "v1"
        ent.vehicle.position.latitude = 39.2
        ent.vehicle.position.longitude = -84.4
        with mock.patch.object(g, "_fetch_raw", return_value=msg.SerializeToString()) as m:
            assert len(g.fetch("vehicles", force_refresh=True)) == 1
        # force_refresh threads through to _fetch_raw.
        assert m.call_args.kwargs.get("force_refresh") is True
