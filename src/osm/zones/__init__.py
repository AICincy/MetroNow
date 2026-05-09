"""Hamilton County MetroNow service zone definitions.

This package also bundles the GeoJSON polygons for each zone plus the
Hamilton County envelope. Polygons are loaded by ``osm.polygons`` via
:mod:`importlib.resources` keyed on this package name (``osm.zones``)
so the resolution works for non-filesystem package backends.
"""

from __future__ import annotations

ZONES: dict[str, dict] = {
    "blue-ash-montgomery": {
        "name": "Blue Ash / Montgomery",
        "bbox": (39.16, -84.44, 39.24, -84.33),
        "description": "Blue Ash, Montgomery, Deer Park, Silverton, Kenwood, Madeira",
        "index-case-street": "O'Leary Avenue",
    },
    "springdale-sharonville": {
        "name": "Springdale / Sharonville",
        "bbox": (39.24, -84.48, 39.32, -84.38),
        "description": "Springdale, Sharonville, Glendale, Evendale, Lincoln Heights",
        "index-case-street": None,
    },
    "northgate-mt-healthy": {
        "name": "Northgate / Mt. Healthy",
        "bbox": (39.22, -84.58, 39.30, -84.48),
        "description": "Mt. Healthy, North College Hill, Finneytown, Northgate",
        "index-case-street": None,
    },
    "forest-park-pleasant-run": {
        "name": "Forest Park / Pleasant Run",
        "bbox": (39.26, -84.56, 39.34, -84.46),
        "description": "Forest Park, Pleasant Run, Greenhills",
        "index-case-street": None,
    },
}

DEFAULT_ZONE = "blue-ash-montgomery"

ZONE_KEYS = list(ZONES.keys())
