"""Tests for the all-or-nothing CAGIS pagination guarantee.

C6.1 from the 2026-05-09 architecture review: if any non-first page
of a CAGIS Feature Server fetch fails, ``fetch_cagis_centerlines``
must propagate (never cache the partial result), so a truncated
centerline set can't silently corrupt mechanical-fix decisions on
the next run.
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def isolated_conflate(tmp_path, monkeypatch):
    from osm import conflate as c

    monkeypatch.setattr(c, "CAGIS_CACHE_DIR", tmp_path / "cagis_cache")
    monkeypatch.setattr(c, "CAGIS_PAGE_SIZE", 2)  # force pagination at 2 features
    return c


def _stub_resp(status: int, payload: dict | None = None):
    class _R:
        status_code = status
        def raise_for_status(self):
            if status >= 400:
                import requests
                raise requests.HTTPError(f"HTTP {status}")
        def json(self):
            return payload or {}
    return _R()


def _feature(i):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[-84.5, 39.0], [-84.4, 39.1]]},
        "properties": {"id": i, "STREETNAME": f"Test St {i}"},
    }


# ---------------------------------------------------------------------------
# Happy path — full pagination completes
# ---------------------------------------------------------------------------

def test_complete_pagination_caches_full_result(isolated_conflate):
    c = isolated_conflate
    # Two full pages of 2 features each, then an empty page → total 4
    responses = [
        _stub_resp(200, {"features": [_feature(1), _feature(2)],
                         "exceededTransferLimit": True}),
        _stub_resp(200, {"features": [_feature(3), _feature(4)],
                         "exceededTransferLimit": True}),
        _stub_resp(200, {"features": []}),
    ]
    with mock.patch.object(c.requests, "get", autospec=True,
                           side_effect=responses):
        out = c.fetch_cagis_centerlines((-84.5, 39.0, -84.4, 39.1))
    assert len(out) == 4

    # Cache file should now exist with the full set.
    cache_files = list((c.CAGIS_CACHE_DIR).glob("*.geojson"))
    assert len(cache_files) == 1


# ---------------------------------------------------------------------------
# Failure paths — never cache partial
# ---------------------------------------------------------------------------

def test_first_page_failure_raises(isolated_conflate):
    c = isolated_conflate
    import requests
    with mock.patch.object(c.requests, "get", autospec=True,
                           side_effect=requests.RequestException("offline")):
        with pytest.raises(c.IncompleteCagisFetch):
            c.fetch_cagis_centerlines((-84.5, 39.0, -84.4, 39.1))

    # Ensure no cache file was written.
    cache_files = list((c.CAGIS_CACHE_DIR).glob("*.geojson"))
    assert cache_files == []


def test_second_page_failure_raises_without_caching_partial(isolated_conflate):
    c = isolated_conflate
    import requests
    responses = [
        _stub_resp(200, {"features": [_feature(1), _feature(2)],
                         "exceededTransferLimit": True}),
        # Mid-stream failure — must NOT be cached as if complete.
        requests.RequestException("upstream timeout"),
    ]
    def _side(*args, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with mock.patch.object(c.requests, "get", autospec=True, side_effect=_side):
        with pytest.raises(c.IncompleteCagisFetch) as excinfo:
            c.fetch_cagis_centerlines((-84.5, 39.0, -84.4, 39.1))
    # The exception message should record how many features were
    # collected before the failure so the operator can decide whether
    # to trust the previous cache.
    assert "page 2" in str(excinfo.value)
    assert "2 feature" in str(excinfo.value)

    cache_files = list((c.CAGIS_CACHE_DIR).glob("*.geojson"))
    assert cache_files == []


def test_existing_complete_cache_survives_a_later_partial_failure(
    isolated_conflate,
):
    """If a complete cache already exists and is fresh, a subsequent
    partial-fetch attempt with force_refresh=True should not corrupt it."""
    c = isolated_conflate
    import requests, json
    # Pre-populate a "good" cache directly (the format mirrors what the
    # successful path writes — a list of features).
    c.CAGIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bbox = (-84.5, 39.0, -84.4, 39.1)
    # Use the public function once with successful responses to seed.
    seed = [
        _stub_resp(200, {"features": [_feature(1)],
                         "exceededTransferLimit": False}),
    ]
    with mock.patch.object(c.requests, "get", autospec=True, side_effect=seed):
        c.fetch_cagis_centerlines(bbox)

    cache_before = list(c.CAGIS_CACHE_DIR.glob("*.geojson"))
    assert len(cache_before) == 1
    contents_before = json.loads(cache_before[0].read_text())

    # Now force-refresh and have it fail mid-stream.
    responses = [
        _stub_resp(200, {"features": [_feature(2), _feature(3)],
                         "exceededTransferLimit": True}),
        requests.RequestException("flaky upstream"),
    ]
    def _side(*args, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with mock.patch.object(c.requests, "get", autospec=True, side_effect=_side):
        with pytest.raises(c.IncompleteCagisFetch):
            c.fetch_cagis_centerlines(bbox, force_refresh=True)

    # Cache must be untouched.
    cache_after = list(c.CAGIS_CACHE_DIR.glob("*.geojson"))
    assert len(cache_after) == 1
    assert json.loads(cache_after[0].read_text()) == contents_before
