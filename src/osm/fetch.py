"""Overpass API data acquisition with retry, mirror fallback, and cache."""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

from .cache import newest_cache, prune_old_cache
from .config import (
    OVERPASS_HEADERS,
    OVERPASS_MIRROR,
    OVERPASS_PRIMARY,
    SANITY_THRESHOLD,
)
from .zones import ZONES


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """Build the Overpass QL query for TIGER-import ways with metadata.

    Selects all highways carrying ``tiger:reviewed=no`` — the standard tag
    indicating TIGER/Line import origin.  The history_filter module then
    determines which of these have actually been reviewed despite keeping
    the tag.
    """
    s, w, n, e = bbox
    return (
        "[out:json][timeout:180];\n"
        'way["highway"]["tiger:reviewed"="no"]\n'
        f"  ({s},{w},{n},{e});\n"
        "out meta geom;\n"
    )


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


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


def fetch_overpass(zone_key: str, out_dir: Path) -> dict:
    """Fetch Overpass data for a zone with retry, mirror fallback, and cache.

    Returns the parsed JSON payload (dict with 'elements' list).
    With ``out meta geom``, each element carries timestamp, version, user,
    uid, changeset, and full geometry.
    """
    zone = ZONES[zone_key]
    query = overpass_query(zone["bbox"])
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
    if payload is None:
        latest = newest_cache(data_dir, zone_key)
        if latest:
            age_s = time.time() - latest.stat().st_mtime
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
    elements = payload.get("elements")
    if not isinstance(elements, list):
        keys_preview = ", ".join(repr(k) for k in list(payload.keys())[:10])
        elem_type = type(elements).__name__ if "elements" in payload else "missing"
        raise RuntimeError(
            f"Overpass payload from {payload_source} has malformed "
            f"'elements' (got {elem_type}, expected list). "
            f"Top-level keys ({len(payload)}): {keys_preview}"
        )
    if len(elements) < SANITY_THRESHOLD:
        log.warning(
            "Only %d elements (sanity threshold %d) — audit may be based on truncated data.",
            len(elements), SANITY_THRESHOLD,
        )
        payload["_under_threshold"] = True
        payload["_element_count"] = len(elements)

    if fresh_fetch:
        out_file = data_dir / f"{zone_key}-raw-{_utc_stamp()}.json"
        with out_file.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        log.info("Saved raw JSON to %s", out_file)
        prune_old_cache(data_dir, zone_key)

    n = len(payload.get("elements", []))
    log.info("Fetched %d elements for %s", n, zone["name"])
    return payload
