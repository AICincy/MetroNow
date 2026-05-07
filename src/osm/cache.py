"""Local caching for Overpass and OSM API responses."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import CACHE_KEEP_NEWEST

log = logging.getLogger(__name__)


def prune_old_cache(data_dir: Path, zone_key: str) -> None:
    """Remove excess cached Overpass snapshots, keeping only the newest."""
    cached = sorted(
        data_dir.glob(f"{zone_key}-raw-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if len(cached) <= CACHE_KEEP_NEWEST:
        return
    for old in cached[:-CACHE_KEEP_NEWEST]:
        try:
            old.unlink()
            log.info("Pruned cache: %s", old.name)
        except OSError as exc:
            log.warning("Could not prune %s: %s", old.name, exc)


def newest_cache(data_dir: Path, zone_key: str) -> Path | None:
    """Return the most recent cached JSON for a zone, or None."""
    cached = sorted(
        data_dir.glob(f"{zone_key}-raw-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return cached[-1] if cached else None
