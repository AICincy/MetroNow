"""Local caching for Overpass and OSM API responses."""

from __future__ import annotations

import time
from pathlib import Path

from .config import CACHE_KEEP_NEWEST


def prune_old_cache(data_dir: Path, zone_key: str) -> None:
    """Remove excess cached Overpass snapshots, keeping only the newest."""
    cached = sorted(
        data_dir.glob(f"{zone_key}_raw_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if len(cached) <= CACHE_KEEP_NEWEST:
        return
    for old in cached[:-CACHE_KEEP_NEWEST]:
        try:
            old.unlink()
            print(f"  Pruned cache: {old.name}")
        except OSError as exc:
            print(f"  Could not prune {old.name}: {exc}")


def newest_cache(data_dir: Path, zone_key: str) -> Path | None:
    """Return the most recent cached JSON for a zone, or None."""
    cached = sorted(
        data_dir.glob(f"{zone_key}_raw_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return cached[-1] if cached else None
