"""Tests for osm.geo — haversine distance, coordinate validation, name normalisation."""

import pytest

from osm.geo import haversine_m, norm_name, valid_latlon


# ---------------------------------------------------------------------------
# haversine_m
# ---------------------------------------------------------------------------

class TestHaversineM:
    """Known-distance pairs validated against external references."""

    def test_same_point_returns_zero(self):
        assert haversine_m(39.1, -84.5, 39.1, -84.5) == 0.0

    def test_short_distance(self):
        # Cincinnati City Hall to Fountain Square: ~350 m
        d = haversine_m(39.1019, -84.5197, 39.1018, -84.5125)
        assert 500 < d < 800

    def test_new_york_to_london(self):
        # JFK to Heathrow: ~5,555 km
        d = haversine_m(40.6413, -73.7781, 51.4700, -0.4543)
        assert 5_500_000 < d < 5_600_000

    def test_north_pole_to_south_pole(self):
        d = haversine_m(90.0, 0.0, -90.0, 0.0)
        # Half the Earth circumference: ~20,015 km
        assert 20_000_000 < d < 20_040_000

    def test_equator_quarter_circle(self):
        d = haversine_m(0.0, 0.0, 0.0, 90.0)
        assert 10_000_000 < d < 10_020_000

    def test_raises_on_invalid_coords(self):
        with pytest.raises(ValueError):
            haversine_m(91.0, 0.0, 0.0, 0.0)

    def test_raises_on_invalid_lon(self):
        with pytest.raises(ValueError):
            haversine_m(0.0, 181.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# valid_latlon
# ---------------------------------------------------------------------------

class TestValidLatlon:

    def test_valid_origin(self):
        assert valid_latlon(0.0, 0.0) is True

    def test_valid_extremes(self):
        assert valid_latlon(90.0, 180.0) is True
        assert valid_latlon(-90.0, -180.0) is True

    def test_cincinnati(self):
        assert valid_latlon(39.1031, -84.5120) is True

    def test_lat_out_of_range(self):
        assert valid_latlon(91.0, 0.0) is False
        assert valid_latlon(-91.0, 0.0) is False

    def test_lon_out_of_range(self):
        assert valid_latlon(0.0, 181.0) is False
        assert valid_latlon(0.0, -181.0) is False


# ---------------------------------------------------------------------------
# norm_name
# ---------------------------------------------------------------------------

class TestNormName:

    def test_basic_normalisation(self):
        assert norm_name("Main Street") == "main street"

    def test_preserves_content(self):
        assert norm_name("I-71") == "i-71"

    def test_strips_whitespace(self):
        assert norm_name("  Elm Ave  ") == "elm ave"

    def test_none_returns_none(self):
        assert norm_name(None) is None

    def test_empty_string_returns_none(self):
        assert norm_name("") is None

    def test_whitespace_only_returns_none(self):
        assert norm_name("   ") is None

    def test_already_lowercase(self):
        assert norm_name("oak lane") == "oak lane"
