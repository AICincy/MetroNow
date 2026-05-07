"""OSM API v0.6 revision history fetching with rate limiting and caching."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from .config import HISTORY_CACHE_DIR, OSM_API_BASE, ensure_config_dirs

RATE_LIMIT_DELAY = 0.5
HISTORY_CACHE_TTL_DAYS = 7


def _cache_path(element_type: str, element_id: int) -> Path:
    h = hashlib.md5(f"{element_type}/{element_id}".encode()).hexdigest()[:4]
    return HISTORY_CACHE_DIR / h[:2] / f"{element_type}_{element_id}.json"


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > HISTORY_CACHE_TTL_DAYS:
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def fetch_way_history(way_id: int) -> dict | None:
    """Fetch the full version history of a way from the OSM API.

    Returns the parsed JSON response, or None on failure.
    Respects rate limiting and uses a local file cache.
    """
    ensure_config_dirs()
    cache = _cache_path("way", way_id)
    cached = _read_cache(cache)
    if cached is not None:
        return cached

    url = f"{OSM_API_BASE}/way/{way_id}/history.json"
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "osm-audit-pipeline/0.1 (Hamilton County TIGER defect audit)",
        })
        if resp.status_code == 410:
            return None
        resp.raise_for_status()
        data = resp.json()
        _write_cache(cache, data)
        time.sleep(RATE_LIMIT_DELAY)
        return data
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"  WARNING: Could not fetch history for way {way_id}: {exc}")
        return None


def fetch_node_history(node_id: int) -> dict | None:
    """Fetch the full version history of a node from the OSM API."""
    ensure_config_dirs()
    cache = _cache_path("node", node_id)
    cached = _read_cache(cache)
    if cached is not None:
        return cached

    url = f"{OSM_API_BASE}/node/{node_id}/history.json"
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "osm-audit-pipeline/0.1 (Hamilton County TIGER defect audit)",
        })
        if resp.status_code == 410:
            return None
        resp.raise_for_status()
        data = resp.json()
        _write_cache(cache, data)
        time.sleep(RATE_LIMIT_DELAY)
        return data
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"  WARNING: Could not fetch history for node {node_id}: {exc}")
        return None


def extract_versions(history_data: dict, element_type: str = "way") -> list[dict]:
    """Extract a chronological list of versions from an OSM history response.

    Each version dict has: version, timestamp, changeset, uid, user, tags, visible.
    """
    elements = history_data.get("elements", [])
    versions = []
    for el in elements:
        if el.get("type") != element_type:
            continue
        versions.append({
            "version": el.get("version"),
            "timestamp": el.get("timestamp"),
            "changeset": el.get("changeset"),
            "uid": el.get("uid"),
            "user": el.get("user"),
            "tags": el.get("tags", {}),
            "visible": el.get("visible", True),
            "nodes": el.get("nodes", []),
        })
    versions.sort(key=lambda v: v["version"] or 0)
    return versions
