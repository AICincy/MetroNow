"""Hamilton County MetroNow service zone definitions."""

from __future__ import annotations

ZONES: dict[str, dict] = {
    "blue_ash_montgomery": {
        "name": "Blue Ash / Montgomery",
        "bbox": (39.16, -84.44, 39.24, -84.33),
        "description": "Blue Ash, Montgomery, Deer Park, Silverton, Kenwood, Madeira",
        "index_case_street": "O'Leary Avenue",
    },
    "springdale_sharonville": {
        "name": "Springdale / Sharonville",
        "bbox": (39.24, -84.48, 39.32, -84.38),
        "description": "Springdale, Sharonville, Glendale, Evendale, Lincoln Heights",
        "index_case_street": None,
    },
    "northgate_mt_healthy": {
        "name": "Northgate / Mt. Healthy",
        "bbox": (39.22, -84.58, 39.30, -84.48),
        "description": "Mt. Healthy, North College Hill, Finneytown, Northgate",
        "index_case_street": None,
    },
    "forest_park_pleasant_run": {
        "name": "Forest Park / Pleasant Run",
        "bbox": (39.26, -84.56, 39.34, -84.46),
        "description": "Forest Park, Pleasant Run, Greenhills",
        "index_case_street": None,
    },
}

DEFAULT_ZONE = "blue_ash_montgomery"

ZONE_KEYS = list(ZONES.keys())
