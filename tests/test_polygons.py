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


class TestPerZonePolygons:
    """Phase 4a stage 2: per-zone polygons are opt-in infrastructure;
    the default clip stays the Hamilton County polygon (stage 1)."""

    def test_default_load_returns_county(self):
        # Stage 1 invariant: load_zone_polygon without prefer_per_zone
        # returns the Hamilton County polygon for every zone — the same
        # clip that won the Forest Park 47% bleed reduction.
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_hamilton_county_polygon,
            load_zone_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        county = load_hamilton_county_polygon()
        for zk in [
            "blue-ash-montgomery", "springdale-sharonville",
            "northgate-mt-healthy", "forest-park-pleasant-run",
        ]:
            poly = load_zone_polygon(zk)
            assert poly is not None
            assert poly.equals_exact(county, tolerance=1e-9), (
                f"Default clip for {zk} must be the county polygon "
                f"(stage 1 invariant)"
            )

    def test_per_zone_opt_in_loads_when_available(self):
        # prefer_per_zone=True returns the per-zone polygon when bundled.
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_hamilton_county_polygon,
            load_zone_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        county = load_hamilton_county_polygon()
        for zk in [
            "blue-ash-montgomery", "springdale-sharonville",
            "northgate-mt-healthy", "forest-park-pleasant-run",
        ]:
            poly = load_zone_polygon(zk, prefer_per_zone=True)
            assert poly is not None
            # Per-zone polygons are tighter than the county (otherwise
            # there's no point opting in).
            assert poly.area < county.area
            # And entirely inside the county after the buffer-clip.
            sym_area = poly.difference(county).area
            assert sym_area / poly.area < 0.01, (
                f"{zk} per-zone polygon must be inside Hamilton County; "
                f"outside fraction: {sym_area / poly.area:.4f}"
            )

    def test_per_zone_opt_in_falls_back_to_county_for_unknown(self):
        # Opt-in for an unknown zone falls through to the county polygon.
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_hamilton_county_polygon,
            load_zone_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        county = load_hamilton_county_polygon()
        fb = load_zone_polygon("nonexistent-zone-xyz", prefer_per_zone=True)
        assert fb.equals_exact(county, tolerance=1e-9)

    def test_per_zone_blue_ash_contains_blue_ash_proper(self):
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_zone_polygon,
            point_in_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        poly = load_zone_polygon("blue-ash-montgomery", prefer_per_zone=True)
        assert point_in_polygon(39.232, -84.378, poly) is True

    def test_per_zone_blue_ash_excludes_northgate(self):
        # Northgate sits at (39.253, -84.594). The Blue Ash per-zone
        # polygon must not include it — the precision gain over the
        # county clip.
        from osm.polygons import (
            SHAPELY_AVAILABLE,
            load_zone_polygon,
            point_in_polygon,
        )
        if not SHAPELY_AVAILABLE:
            pytest.skip("shapely unavailable")
        ba = load_zone_polygon("blue-ash-montgomery", prefer_per_zone=True)
        assert point_in_polygon(39.253, -84.594, ba) is False
