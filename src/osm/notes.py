"""OSM Notes integration.

Surfaces community-reported defects from the OSM Notes API to deduplicate
or elevate the pipeline's own findings. Notes are short, free-text problem
reports any OSM user (or anonymous visitor) can drop on the map; many
TIGER-era residential defects already have an open note that named the
problem before our heuristics did.

Endpoint: ``GET https://api.openstreetmap.org/api/0.6/notes.json``
License: ODbL (same as the rest of OSM).
Auth: none required for read access.
Rate limit: standard OSM API; we obey the User-Agent requirement.

Cache:    one file per bbox under ``~/.config/osm/notes_cache/``, 1-hour TTL
          (notes change much faster than CAGIS centerlines).
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import requests

from osm.cache import (
    cache_path as _bbox_cache_path,
)
from osm.cache import (
    is_cache_fresh,
    read_json_cache,
    write_json_cache,
)
from osm.config import CONFIG_DIR, OVERPASS_HEADERS
from osm.geo import haversine_m
from osm.zones import ZONES

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OSM_NOTES_BASE = "https://api.openstreetmap.org/api/0.6/notes.json"
NOTES_CACHE_DIR = CONFIG_DIR / "notes_cache"
# Notes change much faster than CAGIS centerlines — keep the TTL short.
NOTES_CACHE_TTL_S = 3600  # 1 hour
DEFAULT_LIMIT = 200
DEFAULT_THRESHOLD_M = 50.0

# Re-use the project User-Agent from config so both Overpass and OSM Notes
# present a consistent identity (OSM API requires a meaningful UA).
NOTES_HEADERS = dict(OVERPASS_HEADERS)


# ---------------------------------------------------------------------------
# Fetch + normalize
# ---------------------------------------------------------------------------

def _normalize_note(feature: dict) -> dict | None:
    """Convert an OSM Notes GeoJSON Feature into a flat dict.

    Returns ``None`` if the feature is missing required fields (lat/lon/id).
    """
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        return None
    try:
        lon = float(coords[0])
        lat = float(coords[1])
    except (TypeError, ValueError):
        return None

    props = feature.get("properties") or {}
    note_id = props.get("id") or feature.get("id")
    if note_id is None:
        return None

    raw_comments = props.get("comments") or []
    comments: list[dict[str, Any]] = []
    for c in raw_comments:
        if not isinstance(c, dict):
            continue
        comments.append(
            {
                "text": c.get("text") or c.get("html") or "",
                "user": c.get("user"),
                "date": c.get("date"),
                "action": c.get("action"),
            }
        )

    url = props.get("url") or f"https://www.openstreetmap.org/note/{note_id}"

    return {
        "id": int(note_id) if str(note_id).isdigit() else note_id,
        "lat": lat,
        "lon": lon,
        "status": props.get("status") or "open",
        "date_created": props.get("date_created"),
        "date_closed": props.get("closed_at") or props.get("date_closed"),
        "comments": comments,
        "url": url,
    }


def fetch_notes(
    bbox: tuple[float, float, float, float],
    *,
    status: str = "open",
    limit: int = DEFAULT_LIMIT,
    force_refresh: bool = False,
    timeout: int = 30,
) -> list[dict]:
    """Fetch OSM notes intersecting a (south, west, north, east) bbox.

    Returns a list of flat dicts (see :func:`_normalize_note`). On any HTTP
    error or malformed payload the function logs a warning and returns
    ``[]`` — never raises, so the rest of the pipeline keeps running.

    The OSM API uses ``closed=N`` to control note status:
        * ``status='open'``  → ``closed=0`` (only open notes).
        * ``status='all'``   → ``closed=-1`` (open + recently closed).
        * anything else      → ``closed=0`` (safe default).
    """
    south, west, north, east = bbox
    cache_key = (
        bbox[0], bbox[1], bbox[2], bbox[3],
        # Encode status + limit into the bbox tuple so different queries get
        # different cache files.
    )
    # Use a status-suffixed prefix so an "open" query and an "all" query don't
    # clobber each other's cache.
    prefix = f"notes-{status}-l{int(limit)}"
    path = _bbox_cache_path(NOTES_CACHE_DIR, cache_key, prefix=prefix)

    if not force_refresh and is_cache_fresh(path, NOTES_CACHE_TTL_S):
        cached = read_json_cache(path)
        if isinstance(cached, list):
            log.info(
                "OSM Notes: loaded %d note(s) from cache %s",
                len(cached), path.name,
            )
            return cached

    closed_param = "0" if status == "open" else ("-1" if status == "all" else "0")
    params = {
        # OSM notes API takes bbox as W,S,E,N (lon-min, lat-min, lon-max, lat-max).
        "bbox": f"{west},{south},{east},{north}",
        "limit": str(int(limit)),
        "closed": closed_param,
    }
    url = OSM_NOTES_BASE + "?" + urllib.parse.urlencode(params)

    try:
        resp = requests.get(url, headers=NOTES_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        from . import feed_errors
        reason = "timeout" if "timed out" in str(exc).lower() else (
            "non_json" if isinstance(exc, ValueError) else "http_error"
        )
        feed_errors.record("notes", reason, detail=str(exc))
        log.warning("OSM Notes fetch failed (%s); returning empty list.", exc)
        return []

    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        from . import feed_errors
        feed_errors.record("notes", "malformed_payload",
                           detail="missing 'features' list")
        log.warning(
            "OSM Notes payload missing 'features' list; returning empty list."
        )
        return []

    notes: list[dict] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        n = _normalize_note(feat)
        if n is not None:
            notes.append(n)

    log.info("OSM Notes: fetched %d note(s) for bbox %s", len(notes), bbox)
    write_json_cache(path, notes)
    return notes


def fetch_notes_for_zone(
    zone_key: str,
    *,
    force_refresh: bool = False,
    status: str = "open",
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Fetch OSM notes for a known MetroNow zone."""
    if zone_key not in ZONES:
        raise KeyError(f"Unknown zone {zone_key!r}; choices: {list(ZONES)}")
    bbox = tuple(ZONES[zone_key]["bbox"])
    return fetch_notes(  # type: ignore[arg-type]
        bbox,
        status=status,
        limit=limit,
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------

def annotate_findings_with_notes(
    findings: list[dict],
    notes: list[dict],
    *,
    threshold_m: float = DEFAULT_THRESHOLD_M,
) -> list[dict]:
    """Attach the most recent nearby open note to each finding (mutating).

    For each finding with usable lat/lon, the closest note within
    ``threshold_m`` is attached as ``finding["near_note"]`` (a dict with
    ``id``, ``lat``, ``lon``, ``status``, ``url``, ``distance_m``,
    ``date_created``). When multiple notes are within range we pick the
    most recent one (open notes only). Findings without a coordinate, or
    with no note in range, are left unchanged.
    """
    if not findings or not notes:
        return findings

    open_notes = [n for n in notes if n.get("status") == "open"]
    if not open_notes:
        return findings

    def _date_key(note: dict) -> str:
        return note.get("date_created") or ""

    for f in findings:
        lat = f.get("lat")
        lon = f.get("lon")
        if lat is None or lon is None:
            continue
        try:
            flat = float(lat)
            flon = float(lon)
        except (TypeError, ValueError):
            continue

        in_range: list[tuple[float, dict]] = []
        for n in open_notes:
            try:
                dist = haversine_m(flat, flon, float(n["lat"]), float(n["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            if dist <= threshold_m:
                in_range.append((dist, n))

        if not in_range:
            continue

        # Sort by date_created desc, then by distance asc as a tiebreaker.
        in_range.sort(key=lambda t: (_date_key(t[1]), -t[0]), reverse=True)
        best_dist, best_note = in_range[0]
        f["near_note"] = {
            "id": best_note.get("id"),
            "lat": best_note.get("lat"),
            "lon": best_note.get("lon"),
            "status": best_note.get("status"),
            "url": best_note.get("url"),
            "date_created": best_note.get("date_created"),
            "distance_m": round(float(best_dist), 1),
            "comment_count": len(best_note.get("comments") or []),
        }

    return findings
