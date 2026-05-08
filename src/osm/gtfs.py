"""GTFS feed loader for SORTA — cached, parsed for cross-checks.

Phase 4c provides a lightweight GTFS-stops parser used by the
``misplaced_bus_stops`` detector. A ``highway=bus_stop`` node that
matches a SORTA stop position within a small radius is a valid
off-curb shelter or stop sign placement, not a defect — the original
detector would flag it as misplaced because the OSM-side nearest
drivable vertex was > 20 m away.

The validator in MobilityData/gtfs-validator (Java) is the right
thing to run before treating a feed as authoritative; this module
only parses what we need and trusts the feed. Adoption of the full
Java validator is tracked as a follow-up — see the remediation plan's
Phase 4c.

Source: ``https://www.go-metro.com/uploads/GTFS/google_transit_info.zip``,
SORTA Onestop ID ``o-dngy-southwestohioregionaltransitauthority``,
NTD ID 50012, Wikidata Q7571329.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass

import requests

from .cache import is_cache_fresh
from .config import CONFIG_DIR

log = logging.getLogger(__name__)

# Source of truth for SORTA's published GTFS feed; quarterly cadence
# per their developer page (https://www.go-metro.com/about/developer-data/).
SORTA_GTFS_URL = (
    "https://www.go-metro.com/uploads/GTFS/google_transit_info.zip"
)

# Cache the parsed stops list (not the raw zip) so the detector path
# stays cheap. Refreshing weekly is enough — SORTA's feed updates
# quarterly but route alignment changes can land mid-quarter.
GTFS_CACHE_DIR = CONFIG_DIR / "gtfs_cache"
GTFS_STOPS_CACHE = GTFS_CACHE_DIR / "sorta_stops.json"
GTFS_CACHE_TTL_DAYS = 7


@dataclass
class GtfsStop:
    """One row from SORTA's stops.txt projected to (lat, lon, id, name)."""

    stop_id: str
    name: str
    lat: float
    lon: float


def _coerce_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def parse_stops_csv(text: str) -> list[GtfsStop]:
    """Parse a GTFS stops.txt CSV blob into :class:`GtfsStop` rows."""
    out: list[GtfsStop] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        # Skip parent stations, station entrances, etc. — only physical
        # stops (location_type 0 or empty per GTFS spec).
        loc_type = (row.get("location_type") or "").strip()
        if loc_type and loc_type != "0":
            continue
        lat = _coerce_float(row.get("stop_lat"))
        lon = _coerce_float(row.get("stop_lon"))
        if lat is None or lon is None:
            continue
        out.append(GtfsStop(
            stop_id=row.get("stop_id", "").strip(),
            name=(row.get("stop_name") or "").strip(),
            lat=lat,
            lon=lon,
        ))
    return out


def _read_stops_from_zip(zip_bytes: bytes) -> list[GtfsStop]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf, zf.open("stops.txt") as fh:
        text = fh.read().decode("utf-8-sig")
    return parse_stops_csv(text)


def fetch_sorta_stops(
    *, force_refresh: bool = False, timeout: int = 60,
) -> list[GtfsStop]:
    """Return SORTA's published GTFS stop positions, cached for a week.

    Cache miss / stale → fetch the zip from go-metro.com, extract
    ``stops.txt``, persist a flattened JSON list to disk for the next
    call. Network failure → fall back to the on-disk cache regardless
    of age and log a warning.
    """
    if not force_refresh and is_cache_fresh(
        GTFS_STOPS_CACHE, GTFS_CACHE_TTL_DAYS * 86_400,
    ):
        try:
            with GTFS_STOPS_CACHE.open("r", encoding="utf-8") as fh:
                rows = json.load(fh)
            stops = [GtfsStop(**r) for r in rows]
            log.info("SORTA GTFS: loaded %d stop(s) from cache", len(stops))
            return stops
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            log.warning("GTFS cache unreadable (%s); re-fetching.", exc)

    log.info("SORTA GTFS: fetching %s", SORTA_GTFS_URL)
    try:
        resp = requests.get(SORTA_GTFS_URL, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        stops = _read_stops_from_zip(resp.content)
        log.info("SORTA GTFS: parsed %d stops from feed", len(stops))
        try:
            GTFS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with GTFS_STOPS_CACHE.open("w", encoding="utf-8") as fh:
                json.dump(
                    [s.__dict__ for s in stops], fh, ensure_ascii=False,
                )
        except OSError as exc:
            log.warning("Could not write GTFS cache: %s", exc)
        return stops
    except (requests.RequestException, zipfile.BadZipFile, KeyError) as exc:
        log.warning("SORTA GTFS fetch failed (%s); trying stale cache.", exc)
        if GTFS_STOPS_CACHE.exists():
            try:
                with GTFS_STOPS_CACHE.open("r", encoding="utf-8") as fh:
                    rows = json.load(fh)
                stops = [GtfsStop(**r) for r in rows]
                age_s = time.time() - GTFS_STOPS_CACHE.stat().st_mtime
                log.warning(
                    "SORTA GTFS: using stale cache (%.1f days old, %d stops)",
                    age_s / 86_400, len(stops),
                )
                return stops
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        return []
