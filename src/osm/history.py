"""OSM API v0.6 revision history fetching with rate limiting and caching."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

import httpx
import requests

from .config import HISTORY_CACHE_DIR, OSM_API_BASE, ensure_config_dirs

log = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.5
HISTORY_CACHE_TTL_DAYS = 7
_USER_AGENT = "osm-audit-pipeline/0.1 (Hamilton County TIGER defect audit)"


def _cache_path(element_type: str, element_id: int) -> Path:
    h = hashlib.sha256(f"{element_type}/{element_id}".encode()).hexdigest()[:4]
    return HISTORY_CACHE_DIR / h[:2] / f"{element_type}-{element_id}.json"


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
        resp = requests.get(url, timeout=30, headers={"User-Agent": _USER_AGENT})
        if resp.status_code == 410:
            return None
        resp.raise_for_status()
        data = resp.json()
        _write_cache(cache, data)
        time.sleep(RATE_LIMIT_DELAY)
        return data
    except (requests.RequestException, json.JSONDecodeError) as exc:
        log.warning("Could not fetch history for way %d: %s", way_id, exc)
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
        resp = requests.get(url, timeout=30, headers={"User-Agent": _USER_AGENT})
        if resp.status_code == 410:
            return None
        resp.raise_for_status()
        data = resp.json()
        _write_cache(cache, data)
        time.sleep(RATE_LIMIT_DELAY)
        return data
    except (requests.RequestException, json.JSONDecodeError) as exc:
        log.warning("Could not fetch history for node %d: %s", node_id, exc)
        return None


async def _async_fetch_history(
    element_type: str,
    element_id: int,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> tuple[int, dict | None]:
    """Fetch one element's history with concurrency control. Returns (id, data)."""
    cache = _cache_path(element_type, element_id)
    cached = _read_cache(cache)
    if cached is not None:
        return element_id, cached

    url = f"{OSM_API_BASE}/{element_type}/{element_id}/history.json"
    async with semaphore:
        try:
            resp = await client.get(url)
            if resp.status_code == 410:
                return element_id, None
            resp.raise_for_status()
            data = resp.json()
            _write_cache(cache, data)
            return element_id, data
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log.warning("Could not fetch history for %s %d: %s", element_type, element_id, exc)
            return element_id, None


async def _batch_fetch(
    element_type: str,
    element_ids: list[int],
    max_concurrent: int = 10,
) -> dict[int, dict | None]:
    """Fetch histories for many elements concurrently."""
    ensure_config_dirs()
    semaphore = asyncio.Semaphore(max_concurrent)
    async with httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": _USER_AGENT},
        limits=httpx.Limits(max_connections=max_concurrent),
    ) as client:
        tasks = [
            _async_fetch_history(element_type, eid, client, semaphore)
            for eid in element_ids
        ]
        results = await asyncio.gather(*tasks)
    return dict(results)


def batch_fetch_way_histories(
    way_ids: list[int],
    max_concurrent: int = 10,
) -> dict[int, dict | None]:
    """Fetch way histories concurrently. Returns {way_id: history_data}."""
    if not way_ids:
        return {}
    log.info("Batch fetching %d way histories (max %d concurrent)", len(way_ids), max_concurrent)
    return asyncio.run(_batch_fetch("way", way_ids, max_concurrent))


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
