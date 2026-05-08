"""Overpass API data acquisition with retry, mirror fallback, and cache."""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path

import requests

from .cache import newest_cache, prune_old_cache
from .config import (
    OVERPASS_HEADERS,
    OVERPASS_MIRROR,
    OVERPASS_PRIMARY,
    SANITY_THRESHOLD,
    TIGER_IMPORT_END,
    TIGER_IMPORT_START,
    TIGER_IMPORT_USERS,
)
from .zones import ZONES

log = logging.getLogger(__name__)


def overpass_query(
    bbox: tuple[float, float, float, float],
    *,
    import_only: bool = False,
) -> str:
    """Build the Overpass QL query for TIGER-import ways with metadata.

    Default mode selects ways carrying ``tiger:cfcc`` (Census Feature Class
    Code) — the canonical TIGER-origin marker, present on every TIGER
    import and rarely removed by cleanup bots. ``tiger:reviewed=no`` is
    insufficient as a selector because cleanup bots strip that tag without
    reviewing geometry, leaving real defects invisible (e.g. residential
    streets with a false ``oneway=yes`` carried over from TIGER).

    The tag is an origin marker, not a review-status indicator — the
    history_filter module analyses actual edit history to determine
    whether each way has been meaningfully reviewed.

    Import-only mode (``import_only=True``) uses user/timestamp filters to
    find ways still on their original TIGER import version — a much smaller
    set of definitely-unreviewed ways.
    """
    s, w, n, e = bbox
    if import_only:
        user_filters = "\n".join(
            f'  way["highway"](user:"{user}")'
            f'(if:timestamp()>"{TIGER_IMPORT_START}"'
            f'&&timestamp()<"{TIGER_IMPORT_END}")'
            f"({s},{w},{n},{e});"
            for user in TIGER_IMPORT_USERS
        )
        return (
            "[out:json][timeout:180];\n"
            "(\n"
            f"{user_filters}\n"
            ");\n"
            "out meta geom;\n"
        )

    bbox_str = f"{s},{w},{n},{e}"
    return (
        "[out:json][timeout:180];\n"
        "(\n"
        # Ways: TIGER-origin + oneway candidates (Class A/B/AB/C source set).
        f'  way["highway"]["tiger:cfcc"]({bbox_str});\n'
        f'  way["highway"="residential"]["oneway"="yes"]({bbox_str});\n'
        f'  way["highway"~"^(residential|unclassified|tertiary|service)$"]'
        f'["oneway"="yes"]({bbox_str});\n'
        # Ways needed by rider-impact detectors (full driveable network so
        # access/maxspeed/named-residential checks see all candidates, plus
        # bus-stop nearest-way computation has somewhere to snap to).
        f'  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
        f"unclassified|residential|service)$\"]({bbox_str});\n"
        # Turn restrictions (relations).
        f'  relation["type"="restriction"]({bbox_str});\n'
        # Access barriers, transit stops, building entrances (nodes).
        f'  node["barrier"]({bbox_str});\n'
        f'  node["highway"="bus_stop"]({bbox_str});\n'
        f'  node["entrance"]({bbox_str});\n'
        ");\n"
        "out meta geom;\n"
    )


def _utc_stamp() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def _post_overpass(url: str, query: str) -> requests.Response:
    return requests.post(url, data={"data": query}, headers=OVERPASS_HEADERS, timeout=240)


def _bounded_payload_snippet(payload, *, max_chars: int = 200) -> str:
    if isinstance(payload, list):
        head = payload[:3]
        return f"list[{len(payload)} items], first 3: {repr(head)[:max_chars]}"
    if isinstance(payload, dict):
        keys = list(payload.keys())[:10]
        more = "..." if len(payload) > 10 else ""
        keys_str = ", ".join(repr(k) for k in keys)[:max_chars]
        return f"dict[{len(payload)} keys]: {keys_str}{more}"
    if isinstance(payload, str):
        return payload[:max_chars]
    return repr(payload)[:max_chars]


def fetch_overpass(zone_key: str, out_dir: Path, *, import_only: bool = False) -> dict:
    """Fetch Overpass data for a zone with retry, mirror fallback, and cache.

    Returns the parsed JSON payload (dict with 'elements' list).
    With ``out meta geom``, each element carries timestamp, version, user,
    uid, changeset, and full geometry.
    """
    zone = ZONES[zone_key]
    query = overpass_query(zone["bbox"], import_only=import_only)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    payload: dict | None = None

    attempts = [
        (OVERPASS_PRIMARY, 0),
        (OVERPASS_PRIMARY, 30),
        (OVERPASS_MIRROR, 0),
    ]

    for endpoint, presleep in attempts:
        if presleep:
            log.info("Waiting %ds before retry...", presleep)
            time.sleep(presleep)
        try:
            log.debug("POST %s", endpoint)
            resp = _post_overpass(endpoint, query)
            if resp.status_code == 429:
                log.warning("HTTP 429 rate limit; sleeping 60s before next attempt")
                time.sleep(60)
                last_error = RuntimeError("429 rate limited")
                continue
            resp.raise_for_status()
            try:
                parsed = resp.json()
            except ValueError as exc:
                snippet = resp.text[:500]
                raise RuntimeError(
                    f"Overpass response was not JSON. First 500 chars:\n{snippet}"
                ) from exc
            if parsed is None:
                raise RuntimeError("Overpass returned JSON null")
            payload = parsed
            break
        except (
            requests.RequestException,
            ValueError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            last_error = exc
            log.warning("Attempt failed: %s", exc)
            continue

    fresh_fetch = payload is not None
    payload_source = "live Overpass response"
    cache_age_seconds: float | None = None
    if payload is None:
        latest = newest_cache(data_dir, zone_key)
        if latest:
            age_s = time.time() - latest.stat().st_mtime
            cache_age_seconds = age_s
            age_label = f"{age_s / 3600:.1f}h" if age_s < 86400 else f"{age_s / 86400:.1f}d"
            log.info(
                "Using cached data from %s (age %s). Live query failed.",
                latest.name, age_label,
            )
            if age_s > 14 * 86400:
                log.warning(
                    "Cache is %s old — re-run with network access for fresh data when possible.",
                    age_label,
                )
            with latest.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            payload_source = f"cached file {latest}"
        else:
            raise RuntimeError(
                f"Overpass query failed and no cached data available: {last_error}"
            )

    if not isinstance(payload, dict):
        snippet = _bounded_payload_snippet(payload)
        remediation = (
            "The live Overpass response was malformed; retry later or "
            "check Overpass/network status."
            if fresh_fetch
            else "The cache may be corrupt or manually edited; delete the "
            "file and re-run, or fix it."
        )
        raise RuntimeError(
            f"Overpass payload from {payload_source} is not a JSON object "
            f"(got {type(payload).__name__}). {remediation} Snippet: {snippet}"
        )

    payload.pop("_under_threshold", None)
    payload.pop("_element_count", None)
    payload.pop("_cache_used", None)
    payload.pop("_cache_age_seconds", None)
    elements = payload.get("elements")
    if not isinstance(elements, list):
        keys_preview = ", ".join(repr(k) for k in list(payload.keys())[:10])
        elem_type = type(elements).__name__ if "elements" in payload else "missing"
        raise RuntimeError(
            f"Overpass payload from {payload_source} has malformed "
            f"'elements' (got {elem_type}, expected list). "
            f"Top-level keys ({len(payload)}): {keys_preview}"
        )
    under_threshold = len(elements) < SANITY_THRESHOLD
    if under_threshold:
        log.warning(
            "Only %d elements (sanity threshold %d) — audit may be based on truncated data.",
            len(elements), SANITY_THRESHOLD,
        )
        payload["_under_threshold"] = True
        payload["_element_count"] = len(elements)

    # Bug 6 fix: do not persist a truncated/under-threshold response to disk.
    # Writing it would later be loaded as if it were valid cache (the
    # `_under_threshold` marker is also stripped on reload, so the truncation
    # warning would not re-fire). Skipping the write keeps any prior healthy
    # cache file intact for the fallback path.
    if fresh_fetch and not under_threshold:
        out_file = data_dir / f"{zone_key}-raw-{_utc_stamp()}.json"
        with out_file.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        log.info("Saved raw JSON to %s", out_file)
        prune_old_cache(data_dir, zone_key)

    payload["_cache_used"] = not fresh_fetch
    payload["_cache_age_seconds"] = cache_age_seconds

    n = len(payload.get("elements", []))
    log.info("Fetched %d elements for %s", n, zone["name"])
    return payload
