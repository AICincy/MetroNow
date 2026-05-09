"""Local caching for Overpass and OSM API responses.

Two flavors live here:

1. **Per-zone Overpass snapshot rotation** — :func:`prune_old_cache` and
   :func:`newest_cache`, which keep the most recent N raw Overpass JSONs
   per zone under ``osm-audit-{zone}/data/``.

2. **Bbox-keyed external-API cache** — :func:`bbox_hash`, :func:`cache_path`,
   :func:`is_cache_fresh`, :func:`read_json_cache`, :func:`write_json_cache`.
   Used by :mod:`osm.conflate` (CAGIS), :mod:`osm.notes` (OSM Notes), and
   :mod:`osm.osmose` (Osmose). All three share the same on-disk layout:
   one directory per source under ``~/.config/osm/{name}_cache/``, files
   named ``{prefix}-{bbox-hash}.json``, with a per-source TTL.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import CACHE_KEEP_NEWEST

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-zone Overpass snapshot rotation (existing helpers)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Bbox-keyed external-API cache
# ---------------------------------------------------------------------------

def bbox_hash(bbox: tuple[float, float, float, float]) -> str:
    """Stable short hash for cache filenames keyed by bbox.

    Six-decimal precision is enough for the ~10 cm hashing granularity we
    need; the same zone bbox always produces the same key.
    """
    payload = ",".join(f"{v:.6f}" for v in bbox)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def cache_path(
    cache_dir: Path,
    bbox: tuple[float, float, float, float],
    *,
    prefix: str,
    suffix: str = "json",
) -> Path:
    """Compute the on-disk path for a bbox-keyed cache file."""
    return cache_dir / f"{prefix}-{bbox_hash(bbox)}.{suffix}"


def is_cache_fresh(path: Path, ttl_seconds: float) -> bool:
    """True when ``path`` exists and its mtime is within ``ttl_seconds``."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_seconds


def read_json_cache(path: Path) -> Any | None:
    """Read a JSON cache file, returning ``None`` if unreadable.

    Logs at WARNING for unreadable existing files (likely corruption).
    Logs at DEBUG for the more common ``FileNotFoundError`` path.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        log.debug("Cache miss: %s", path.name)
        return None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cache %s unreadable (%s); will re-fetch.", path.name, exc)
        return None


def write_json_cache(path: Path, payload: Any) -> None:
    """Write a JSON payload to the cache file atomically.

    Implementation: write to a sibling tempfile in the same directory,
    fsync, then ``os.replace`` over the target. This guarantees that
    readers either see the previous complete file or the new complete
    file, never a truncated mid-write state. Same-directory tempfile
    is required so ``os.replace`` is atomic (it falls back to a
    cross-device copy otherwise).
    """
    import os
    import tempfile

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create cache dir for %s: %s", path, exc)
        return

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_name = fh.name
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        log.warning("Could not write cache %s atomically: %s", path, exc)
        if tmp_name:
            import contextlib
            with contextlib.suppress(OSError):
                Path(tmp_name).unlink()
