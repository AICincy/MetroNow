"""Tests for osm.tiger2024 — TIGER/Line 2024 second-source conflation.

Most tests synthesize a minimal Esri shapefile + dBASE III file in a tmp
directory rather than committing a binary fixture. The format subset we
exercise (PolyLine type 3 + dBASE III with C/N fields) matches what the
production reader supports.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixture helpers — write tiny in-memory .shp + .dbf files
# ---------------------------------------------------------------------------

def _write_shapefile(
    path: Path, polylines: list[list[tuple[float, float]]],
) -> None:
    """Write a PolyLine (shape type 3) shapefile with the given features.

    Each polyline is a list of (lon, lat) vertices. Output files get the
    .shp / .shx / .prj siblings the reader expects.
    """
    # File body. Each record:
    #   record header: rec_num BE int32, content_len BE int32 (16-bit words)
    #   content: shape_type LE int32 = 3
    #            bbox 4 doubles LE (xmin, ymin, xmax, ymax)
    #            num_parts int32 LE = 1
    #            num_points int32 LE
    #            parts int32 LE = [0]
    #            points 16-byte (X, Y) doubles
    body = bytearray()
    file_xmin = float("inf")
    file_ymin = float("inf")
    file_xmax = float("-inf")
    file_ymax = float("-inf")
    for rec_num, pts in enumerate(polylines, start=1):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        file_xmin = min(file_xmin, xmin)
        file_ymin = min(file_ymin, ymin)
        file_xmax = max(file_xmax, xmax)
        file_ymax = max(file_ymax, ymax)
        content = bytearray()
        content += struct.pack("<i", 3)
        content += struct.pack("<dddd", xmin, ymin, xmax, ymax)
        content += struct.pack("<ii", 1, len(pts))
        content += struct.pack("<i", 0)
        for x, y in pts:
            content += struct.pack("<dd", x, y)
        # 16-bit words.
        content_len_words = len(content) // 2
        body += struct.pack(">ii", rec_num, content_len_words)
        body += content

    file_len_words = (100 + len(body)) // 2
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, file_len_words)
    struct.pack_into("<i", header, 28, 1000)  # version
    struct.pack_into("<i", header, 32, 3)     # shape type 3 (PolyLine)
    struct.pack_into(
        "<dddd", header, 36,
        file_xmin if polylines else 0.0,
        file_ymin if polylines else 0.0,
        file_xmax if polylines else 0.0,
        file_ymax if polylines else 0.0,
    )
    # zmin, zmax, mmin, mmax = 0
    with path.open("wb") as fh:
        fh.write(bytes(header))
        fh.write(bytes(body))

    # Minimal .prj — NAD83 (TIGER ships in EPSG:4269).
    path.with_suffix(".prj").write_text(
        'GEOGCS["NAD83",DATUM["North_American_Datum_1983"],'
        'PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]]',
        encoding="ascii",
    )


def _write_dbf(
    path: Path,
    fields: list[tuple[str, str, int]],
    records: list[dict],
) -> None:
    """Write a minimal dBASE III .dbf with the given fields and records."""
    header_len = 32 + 32 * len(fields) + 1  # +1 for terminator
    record_len = 1 + sum(f[2] for f in fields)  # +1 deletion flag
    out = bytearray()
    # Header: version, last_update_yymmdd, num_records, header_len, record_len
    out += bytes([0x03, 25, 1, 1])  # version 3, date 2025-01-01
    out += struct.pack("<IHH", len(records), header_len, record_len)
    out += b"\x00" * 20  # reserved + flags
    for name, ftype, flen in fields:
        name_b = name.encode("ascii")[:11]
        name_b += b"\x00" * (11 - len(name_b))
        out += name_b
        out += ftype.encode("ascii")
        out += b"\x00\x00\x00\x00"  # field address (unused)
        out += bytes([flen, 0])      # length, decimals
        out += b"\x00" * 14
    out += b"\x0d"  # terminator
    for row in records:
        out += b" "  # not deleted
        for name, ftype, flen in fields:
            val = row.get(name)
            if val is None:
                out += b" " * flen
            else:
                s = str(val)
                if ftype in ("N", "F"):
                    # Right-justify numerics
                    s = s[-flen:].rjust(flen, " ")
                else:
                    s = s[:flen].ljust(flen, " ")
                out += s.encode("ascii", errors="replace")
    path.write_bytes(bytes(out))


@pytest.fixture
def tiger_shp(tmp_path: Path) -> Path:
    """Synthesize a 3-feature TIGER-shaped shapefile.

    Feature 1: OAK ST     S1400 east-west line at y=39.20  (residential)
    Feature 2: I-71       S1100 east-west line at y=39.30  (motorway)
    Feature 3: COUNTY 12  S1500 east-west line at y=39.40  (unclassified)
    """
    shp = tmp_path / "tl_2024_39061_roads.shp"
    polylines = [
        [(-84.40, 39.20), (-84.39, 39.20)],
        [(-84.40, 39.30), (-84.39, 39.30)],
        [(-84.40, 39.40), (-84.39, 39.40)],
    ]
    _write_shapefile(shp, polylines)
    _write_dbf(
        shp.with_suffix(".dbf"),
        fields=[
            ("LINEARID", "C", 22),
            ("FULLNAME", "C", 100),
            ("MTFCC", "C", 5),
            ("RTTYP", "C", 1),
        ],
        records=[
            {"LINEARID": "1101000000001", "FULLNAME": "Oak St",
             "MTFCC": "S1400", "RTTYP": "M"},
            {"LINEARID": "1101000000002", "FULLNAME": "I- 71",
             "MTFCC": "S1100", "RTTYP": "I"},
            {"LINEARID": "1101000000003", "FULLNAME": "County 12",
             "MTFCC": "S1500", "RTTYP": "C"},
        ],
    )
    return shp


# ---------------------------------------------------------------------------
# Reader tests
# ---------------------------------------------------------------------------

class TestReader:

    def test_polyline_reader_roundtrips_geometry(self, tiger_shp: Path):
        from osm.tiger2024 import _read_shapefile_polylines
        polylines = _read_shapefile_polylines(tiger_shp)
        assert len(polylines) == 3
        first = polylines[0]
        # [lat, lon] order — y/lat second after the lon/x.
        assert first[0] == [pytest.approx(39.20), pytest.approx(-84.40)]
        assert first[1] == [pytest.approx(39.20), pytest.approx(-84.39)]

    def test_dbf_reader_extracts_fields(self, tiger_shp: Path):
        from osm.tiger2024 import _read_dbf_records
        rows = _read_dbf_records(tiger_shp.with_suffix(".dbf"))
        assert len(rows) == 3
        assert rows[0]["LINEARID"] == "1101000000001"
        assert rows[0]["FULLNAME"] == "Oak St"
        assert rows[0]["MTFCC"] == "S1400"
        assert rows[1]["MTFCC"] == "S1100"
        assert rows[2]["MTFCC"] == "S1500"

    def test_load_features_combines_geom_and_props(self, tiger_shp: Path):
        from osm.tiger2024 import load_tiger2024_features
        features = load_tiger2024_features(shp_path=tiger_shp)
        assert len(features) == 3
        f0 = features[0]
        assert f0["properties"]["MTFCC"] == "S1400"
        assert len(f0["geometry"]) == 2

    def test_features_in_bbox_filters(self, tiger_shp: Path):
        from osm.tiger2024 import features_in_bbox, load_tiger2024_features
        features = load_tiger2024_features(shp_path=tiger_shp)
        # Only the y=39.20 feature falls inside this bbox.
        sub = features_in_bbox(features, (39.18, -84.41, 39.22, -84.38))
        assert len(sub) == 1
        assert sub[0]["properties"]["FULLNAME"] == "Oak St"


# ---------------------------------------------------------------------------
# Match tests
# ---------------------------------------------------------------------------

class TestMatch:

    def test_aligned_same_name_high_confidence(self, tiger_shp: Path):
        from osm.tiger2024 import (
            build_tiger_index,
            load_tiger2024_features,
            match_way,
        )
        feats = load_tiger2024_features(shp_path=tiger_shp)
        idx = build_tiger_index(feats)
        osm_way = {
            "id": 1,
            "name": "Oak Street",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m["tiger_name"] == "Oak St"
        assert m["tiger_mtfcc"] == "S1400"
        assert m["confidence"] >= 0.8
        assert m["hausdorff_m"] < 1.0

    def test_name_mismatch_lowers_confidence(self, tiger_shp: Path):
        from osm.tiger2024 import (
            build_tiger_index,
            load_tiger2024_features,
            match_way,
        )
        idx = build_tiger_index(load_tiger2024_features(shp_path=tiger_shp))
        osm_way = {
            "id": 2,
            "name": "Birch Boulevard",
            "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is not None
        assert m["name_similarity"] < 0.4
        assert m["confidence"] < 0.7

    def test_geometry_mismatch_no_match(self, tiger_shp: Path):
        # Way ~50m offset from any TIGER feature — outside 30m buffer.
        from osm.tiger2024 import (
            build_tiger_index,
            load_tiger2024_features,
            match_way,
        )
        idx = build_tiger_index(load_tiger2024_features(shp_path=tiger_shp))
        osm_way = {
            "id": 3,
            "name": "Oak Street",
            "geometry": [[39.2005, -84.4000], [39.2005, -84.3900]],
        }
        m = match_way(osm_way, idx)
        assert m is None

    def test_conflate_attaches_match_to_every_way(self, tiger_shp: Path):
        from osm.tiger2024 import (
            build_tiger_index,
            conflate_with_tiger,
            load_tiger2024_features,
        )
        idx = build_tiger_index(load_tiger2024_features(shp_path=tiger_shp))
        ways = [
            {
                "id": 1, "name": "Oak Street",
                "geometry": [[39.2000, -84.4000], [39.2000, -84.3900]],
            },
            {
                "id": 2, "name": "Far Away",
                "geometry": [[40.0, -85.0], [40.0001, -85.0]],
            },
        ]
        conflate_with_tiger(ways, idx)
        assert ways[0]["tiger_match"] is not None
        assert ways[1]["tiger_match"] is None


# ---------------------------------------------------------------------------
# MTFCC mapping tests
# ---------------------------------------------------------------------------

class TestMtfccMapping:

    def test_known_codes_map_to_highway(self):
        from osm.tiger2024 import suggested_highway_for_mtfcc
        assert suggested_highway_for_mtfcc("S1100") == "motorway"
        assert suggested_highway_for_mtfcc("S1200") == "primary"
        assert suggested_highway_for_mtfcc("S1500") == "unclassified"
        assert suggested_highway_for_mtfcc("S1640") == "service"
        assert suggested_highway_for_mtfcc("S1730") == "service"

    def test_ambiguous_s1400_returns_none(self):
        from osm.tiger2024 import is_ambiguous_mtfcc, suggested_highway_for_mtfcc
        assert suggested_highway_for_mtfcc("S1400") is None
        assert is_ambiguous_mtfcc("S1400") is True

    def test_unknown_mtfcc_returns_none(self):
        from osm.tiger2024 import is_ambiguous_mtfcc, suggested_highway_for_mtfcc
        assert suggested_highway_for_mtfcc("S9999") is None
        assert suggested_highway_for_mtfcc(None) is None
        assert is_ambiguous_mtfcc("S9999") is False
        assert is_ambiguous_mtfcc(None) is False


# ---------------------------------------------------------------------------
# Review-layer integration: TIGER fallback fixes
# ---------------------------------------------------------------------------

class TestReviewIntegration:

    def test_set_name_tiger_when_no_cagis(self):
        from osm.review import proposed_fixes_for_way
        way = {
            "id": 1000,
            "defect_class": "C",
            "highway": "residential",
            "name": "Maple Road",
            "name_display": "Maple Road",
            "cagis_match": None,
            "tiger_match": {
                "tiger_id": "1101000099999",
                "tiger_name": "Mapleview Rd",
                "tiger_mtfcc": "S1400",
                "tiger_rttyp": "M",
                "confidence": 0.91,
                "hausdorff_m": 1.5,
                "name_similarity": 0.7,
                "name_match": False,
            },
        }
        fixes = proposed_fixes_for_way(way)
        kinds = {f["kind"] for f in fixes}
        assert "set_name_tiger" in kinds
        name_fix = next(f for f in fixes if f["kind"] == "set_name_tiger")
        # TIGER name fixes always require human review.
        assert name_fix["requires_human_review"] is True
        assert name_fix["source_evidence"]["tiger_id"] == "1101000099999"

    def test_no_tiger_fix_when_high_confidence_cagis_present(self):
        # TIGER must NEVER override a high-confidence CAGIS match.
        from osm.review import proposed_fixes_for_way
        way = {
            "id": 1001,
            "defect_class": "C",
            "highway": "residential",
            "name": "Oak Street",
            "name_display": "Oak Street",
            "cagis_match": {
                "cagis_id": 42,
                "cagis_name": "OAK ST",
                "cagis_oneway": "no",
                "confidence": 0.92,
                "hausdorff_m": 1.0,
                "name_similarity": 0.95,
                "name_match": True,
            },
            "tiger_match": {
                "tiger_id": "1101000099999",
                "tiger_name": "Maple Rd",  # disagrees, but should be ignored
                "tiger_mtfcc": "S1400",
                "confidence": 0.91,
                "hausdorff_m": 1.5,
                "name_similarity": 0.3,
                "name_match": False,
            },
        }
        fixes = proposed_fixes_for_way(way)
        kinds = {f["kind"] for f in fixes}
        assert "set_name_tiger" not in kinds
        assert "reclass_highway_tiger" not in kinds

    def test_reclass_highway_tiger_for_known_mtfcc(self):
        from osm.review import proposed_fixes_for_way
        way = {
            "id": 1002,
            "defect_class": "C",
            "highway": "residential",  # OSM thinks this is residential…
            "name": "Old County Hwy 12",
            "name_display": "Old County Hwy 12",
            "cagis_match": None,
            "tiger_match": {
                "tiger_id": "1101000099999",
                "tiger_name": "Old County Hwy 12",
                "tiger_mtfcc": "S1500",  # …but TIGER says unclassified.
                "confidence": 0.9,
                "hausdorff_m": 2.0,
                "name_similarity": 1.0,
                "name_match": True,
            },
        }
        fixes = proposed_fixes_for_way(way)
        kinds = {f["kind"] for f in fixes}
        assert "reclass_highway_tiger" in kinds
        rc = next(f for f in fixes if f["kind"] == "reclass_highway_tiger")
        assert rc["changes"]["highway"] == "unclassified"
        assert rc["requires_human_review"] is True

    def test_no_reclass_for_ambiguous_s1400(self):
        from osm.review import proposed_fixes_for_way
        way = {
            "id": 1003,
            "defect_class": "C",
            "highway": "service",
            "name": "Oak Street",
            "name_display": "Oak Street",
            "cagis_match": None,
            "tiger_match": {
                "tiger_id": "1101000099999",
                "tiger_name": "Oak St",
                "tiger_mtfcc": "S1400",  # ambiguous: residential vs unclassified
                "confidence": 0.9,
                "hausdorff_m": 1.0,
                "name_similarity": 1.0,
                "name_match": True,
            },
        }
        fixes = proposed_fixes_for_way(way)
        kinds = {f["kind"] for f in fixes}
        assert "reclass_highway_tiger" not in kinds


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestDegradation:

    def test_missing_shapefile_returns_empty(self, tmp_path: Path):
        from osm.tiger2024 import load_tiger2024_features
        out = load_tiger2024_features(shp_path=tmp_path / "missing.shp")
        assert out == []

    def test_malformed_dbf_does_not_raise(self, tmp_path: Path):
        # Write a valid .shp but a truncated .dbf — features should come back
        # with empty properties dicts but the geometry still present.
        from osm.tiger2024 import load_tiger2024_features
        shp = tmp_path / "tiny.shp"
        _write_shapefile(shp, [[(-84.40, 39.20), (-84.39, 39.20)]])
        shp.with_suffix(".dbf").write_bytes(b"\x00" * 8)  # truncated header
        feats = load_tiger2024_features(shp_path=shp)
        assert len(feats) == 1
        assert feats[0]["geometry"]
        assert feats[0]["properties"] in ({}, {"": None})

    def test_network_unreachable_falls_back(self, tmp_path: Path, monkeypatch):
        from osm import tiger2024
        # Force download path: shp_path=None and patch fetch to raise.
        def _explode(*a, **kw):
            raise tiger2024.requests.RequestException("DNS failure")
        monkeypatch.setattr(tiger2024, "fetch_tiger2024", _explode)
        out = tiger2024.load_tiger2024_features(shp_path=None)
        assert out == []

    def test_module_reload_without_shapely(self):
        """Force-import osm.tiger2024 with shapely shadowed — the index
        layer must degrade to empty without crashing."""
        import importlib
        saved = {
            k: sys.modules.get(k)
            for k in (
                "osm.tiger2024", "shapely", "shapely.geometry", "shapely.strtree",
            )
        }
        try:
            sys.modules.pop("osm.tiger2024", None)
            sys.modules["shapely"] = None  # type: ignore[assignment]
            sys.modules["shapely.geometry"] = None  # type: ignore[assignment]
            sys.modules["shapely.strtree"] = None  # type: ignore[assignment]
            with mock.patch.dict(sys.modules, {
                "shapely": None,
                "shapely.geometry": None,
                "shapely.strtree": None,
            }):
                tiger_mod = importlib.import_module("osm.tiger2024")
                tiger_mod = importlib.reload(tiger_mod)
                assert tiger_mod.SHAPELY_AVAILABLE is False
                idx = tiger_mod.build_tiger_index([])
                assert len(idx) == 0
                assert idx.available is False
                osm_way = {
                    "id": 1, "name": "Oak Street",
                    "geometry": [[39.20, -84.40], [39.20, -84.39]],
                }
                assert tiger_mod.match_way(osm_way, idx) is None
                ways = [osm_way]
                tiger_mod.conflate_with_tiger(ways, idx)
                assert ways[0]["tiger_match"] is None
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            sys.modules.pop("osm.tiger2024", None)
