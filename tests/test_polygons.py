"""Tests for osm.polygons — Phase 4a polygon clip."""

from __future__ import annotations

import pytest


class TestPolygonContainment:
    """Sanity checks against the bundled Hamilton County polygon."""

    def test_bundled_polygon_loads(self):
        from osm.polygons import SHAPELY_AVAILABLE, load_hamilton_county_polygon
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        poly = load_hamilton_county_polygon()
        assert poly is not None
        # Basic sanity: county area is non-trivial and the centroid is
        # somewhere near Cincinnati, not at (0, 0).
        c = poly.centroid
        assert -85.0 < c.x < -84.0
        assert 39.0 < c.y < 39.5

    def test_blue_ash_inside_county(self):
        # Blue Ash sits well inside Hamilton County.
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_hamilton_county_polygon,
            point_in_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        poly = load_hamilton_county_polygon()
        assert point_in_polygon(39.232, -84.378, poly) is True

    def test_butler_county_outside(self):
        # West Chester Township (Butler County, just north of Hamilton).
        # This is exactly the Forest Park bbox bleed we're trying to remove.
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_hamilton_county_polygon,
            point_in_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        poly = load_hamilton_county_polygon()
        assert point_in_polygon(39.34, -84.46, poly) is False

    def test_point_in_polygon_handles_none(self):
        from osm.polygons import point_in_polygon
        # No polygon → "keep". The clip wrapper handles the disabled case;
        # the helper itself defaults to True so no caller silently drops
        # everything if shapely is missing.
        assert point_in_polygon(39.2, -84.4, None) is True


class TestClipElements:
    """clip_elements_to_polygon should drop ways/nodes outside the polygon
    and keep relations untouched."""

    def _setup(self):
        from osm.polygons import SHAPELY_AVAILABLE, load_hamilton_county_polygon
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        return load_hamilton_county_polygon()

    def test_clip_drops_way_outside_county(self):
        from osm.polygons import clip_elements_to_polygon
        poly = self._setup()
        elements = [
            {
                "type": "way",
                "id": 100,
                # Inside Hamilton County (Blue Ash)
                "geometry": [
                    {"lat": 39.232, "lon": -84.378},
                    {"lat": 39.233, "lon": -84.377},
                ],
            },
            {
                "type": "way",
                "id": 200,
                # Outside Hamilton County (Butler County north of border)
                "geometry": [
                    {"lat": 39.34, "lon": -84.46},
                    {"lat": 39.341, "lon": -84.461},
                ],
            },
        ]
        kept, stats = clip_elements_to_polygon(elements, poly)
        assert stats["clipped"] is True
        assert stats["kept"] == 1
        assert stats["dropped_total"] == 1
        kept_ids = [e["id"] for e in kept]
        assert kept_ids == [100]

    def test_clip_keeps_relations(self):
        # Relations are not centroidable cheaply; clip leaves them in.
        from osm.polygons import clip_elements_to_polygon
        poly = self._setup()
        elements = [
            {"type": "relation", "id": 999, "tags": {"type": "restriction"}},
        ]
        kept, stats = clip_elements_to_polygon(elements, poly)
        assert len(kept) == 1
        assert kept[0]["id"] == 999

    def test_clip_handles_node_centroid(self):
        from osm.polygons import clip_elements_to_polygon
        poly = self._setup()
        elements = [
            {"type": "node", "id": 1, "lat": 39.232, "lon": -84.378},   # in
            {"type": "node", "id": 2, "lat": 39.34, "lon": -84.46},     # out (Butler)
        ]
        kept, stats = clip_elements_to_polygon(elements, poly)
        assert stats["kept"] == 1
        assert kept[0]["id"] == 1

    def test_clip_preserves_no_centroid_elements(self):
        # An element with no usable geometry / coordinates should be kept;
        # we don't have evidence to drop it and dropping might silently
        # remove turn-restriction member references.
        from osm.polygons import clip_elements_to_polygon
        poly = self._setup()
        elements = [
            {"type": "way", "id": 7, "geometry": []},
        ]
        kept, stats = clip_elements_to_polygon(elements, poly)
        assert stats["kept"] == 1
        assert stats["no_centroid"] == 1

    def test_clip_no_op_when_polygon_none(self):
        # Polygon unavailable → return input unchanged with stats marker.
        from osm.polygons import clip_elements_to_polygon
        elements = [{"type": "way", "id": 1, "geometry": [{"lat": 0, "lon": 0}]}]
        kept, stats = clip_elements_to_polygon(elements, None)
        assert kept == elements
        assert stats["clipped"] is False
