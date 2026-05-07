"""Geographic utilities: haversine, coordinate validation, name normalisation."""

from __future__ import annotations

import math


def valid_latlon(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    if not (valid_latlon(lat1, lon1) and valid_latlon(lat2, lon2)):
        raise ValueError(
            f"Invalid lat/lon for haversine: ({lat1},{lon1}) ({lat2},{lon2})"
        )
    R = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def norm_name(name: str | None) -> str | None:
    """Case-insensitive name normalisation for street grouping."""
    if not name:
        return None
    s = name.strip()
    return s.lower() if s else None
