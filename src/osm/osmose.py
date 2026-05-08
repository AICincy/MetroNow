"""Osmose-QA integration.

Surfaces issues already flagged by the Osmose-QA project so the pipeline
can avoid auto-submitting fixes to ways that the wider community is
already aware of. Osmose flags every Osmose-detected issue against
specific OSM elements (ways, nodes, relations) so we can index by
element id and check membership cheaply.

Endpoint:
    ``GET https://osmose.openstreetmap.fr/api/0.3/issues``
        with ``bbox=W,S,E,N&full=true&limit=N``.

License: ODbL-derived (Osmose data is created from OSM).
Auth: none required.
Rate limit: unpublished public endpoint; obey UA.

Cache: one file per bbox under ``~/.config/osm/osmose_cache/``, 24-hour TTL.
"""

from __future__ import annotations

import logging
import urllib.parse
from collections import defaultdict
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
from osm.zones import ZONES

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OSMOSE_BASE = "https://osmose.openstreetmap.fr/api/0.3/issues"
OSMOSE_ISSUE_URL_TMPL = "https://osmose.openstreetmap.fr/issue/{uuid}"
OSMOSE_CACHE_DIR = CONFIG_DIR / "osmose_cache"
OSMOSE_CACHE_TTL_S = 24 * 3600  # 24 hours
DEFAULT_LIMIT = 500

OSMOSE_HEADERS = dict(OVERPASS_HEADERS)


# ---------------------------------------------------------------------------
# Fetch + normalize
# ---------------------------------------------------------------------------

def _osm_id_buckets(issue: dict) -> dict[str, list[int]]:
    """Extract way/node/relation ids from an Osmose issue (best-effort).

    Osmose's ``full=true`` payload places the affected OSM elements under
    ``elems`` (newer schema) or ``osm_ids`` (legacy alias) — handle both
    plus a top-level ``elements`` list as a fallback. Each entry can be
    either a dict like ``{"type": "way", "id": 123}`` or a string like
    ``"way/123"``.
    """
    ways: list[int] = []
    nodes: list[int] = []
    relations: list[int] = []

    def _add(el_type: str | None, el_id: Any) -> None:
        if el_type is None or el_id is None:
            return
        try:
            iid = int(el_id)
        except (TypeError, ValueError):
            return
        et = el_type.lower()
        if et == "way":
            ways.append(iid)
        elif et == "node":
            nodes.append(iid)
        elif et == "relation":
            relations.append(iid)

    raw = issue.get("elems") or issue.get("osm_ids") or issue.get("elements")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                _add(entry.get("type"), entry.get("id"))
            elif isinstance(entry, str) and "/" in entry:
                etype, _, eid = entry.partition("/")
                _add(etype, eid)
    elif isinstance(raw, dict):
        # legacy: {"ways": [...], "nodes": [...], "relations": [...]}
        for key, dest in (
            ("ways", ways), ("nodes", nodes), ("relations", relations),
        ):
            for v in raw.get(key) or []:
                try:
                    dest.append(int(v))
                except (TypeError, ValueError):
                    continue

    return {"ways": ways, "nodes": nodes, "relations": relations}


def _normalize_issue(issue: dict) -> dict | None:
    """Convert one Osmose issue dict into a flat normalized form.

    Returns ``None`` for issues missing both an id/uuid and any element
    reference — those are useless for our matcher.
    """
    if not isinstance(issue, dict):
        return None
    issue_uuid = issue.get("uuid") or issue.get("id")
    item = issue.get("item")
    item_title: str | None = None
    raw_title = issue.get("title") or issue.get("subtitle")
    if isinstance(raw_title, dict):
        # Osmose uses a {"auto": "...", "en": "...", ...} structure for some titles.
        item_title = raw_title.get("auto") or raw_title.get("en")
        if item_title is None:
            for v in raw_title.values():
                if isinstance(v, str) and v:
                    item_title = v
                    break
    elif isinstance(raw_title, str):
        item_title = raw_title

    raw_subtitle = issue.get("subtitle")
    subtitle: str | None = None
    if isinstance(raw_subtitle, dict):
        subtitle = raw_subtitle.get("auto") or raw_subtitle.get("en")
    elif isinstance(raw_subtitle, str):
        subtitle = raw_subtitle

    osm_ids = _osm_id_buckets(issue)
    if (
        issue_uuid is None
        and not osm_ids["ways"]
        and not osm_ids["nodes"]
        and not osm_ids["relations"]
    ):
        return None

    lat = issue.get("lat")
    lon = issue.get("lon")
    try:
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lat = None
        lon = None

    url = (
        OSMOSE_ISSUE_URL_TMPL.format(uuid=issue_uuid) if issue_uuid else
        "https://osmose.openstreetmap.fr/"
    )

    return {
        "id": issue_uuid,
        "item": str(item) if item is not None else None,
        "item_title": item_title,
        "lat": lat,
        "lon": lon,
        "subtitle": subtitle,
        "osm_ids": osm_ids,
        "url": url,
    }


def fetch_issues(
    bbox: tuple[float, float, float, float],
    *,
    item_filter: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    force_refresh: bool = False,
    timeout: int = 30,
) -> list[dict]:
    """Fetch Osmose issues intersecting a (south, west, north, east) bbox.

    Returns a list of normalized issue dicts. On any HTTP error or
    malformed payload, logs a warning and returns ``[]`` — graceful
    degradation, never raises.

    ``item_filter`` is a list of Osmose item codes (e.g. ``["3070"]``) to
    include. When ``None`` all issues are returned.
    """
    south, west, north, east = bbox

    items_key = ",".join(sorted(item_filter)) if item_filter else "all"
    prefix = f"issues-l{int(limit)}-{items_key}"
    path = _bbox_cache_path(OSMOSE_CACHE_DIR, bbox, prefix=prefix)

    if not force_refresh and is_cache_fresh(path, OSMOSE_CACHE_TTL_S):
        cached = read_json_cache(path)
        if isinstance(cached, list):
            log.info(
                "Osmose: loaded %d issue(s) from cache %s",
                len(cached), path.name,
            )
            return cached

    params: dict[str, str] = {
        # Osmose takes bbox as W,S,E,N (lon-min, lat-min, lon-max, lat-max).
        "bbox": f"{west},{south},{east},{north}",
        "full": "true",
        "limit": str(int(limit)),
    }
    if item_filter:
        params["item"] = ",".join(item_filter)
    url = OSMOSE_BASE + "?" + urllib.parse.urlencode(params)

    try:
        resp = requests.get(url, headers=OSMOSE_HEADERS, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Osmose fetch failed (%s); returning empty list.", exc)
        return []

    if not isinstance(data, dict):
        log.warning("Osmose payload was not a JSON object; returning empty list.")
        return []
    raw_issues = data.get("issues")
    if not isinstance(raw_issues, list):
        log.warning("Osmose payload missing 'issues' list; returning empty list.")
        return []

    issues: list[dict] = []
    for raw in raw_issues:
        n = _normalize_issue(raw) if isinstance(raw, dict) else None
        if n is not None:
            issues.append(n)

    log.info("Osmose: fetched %d issue(s) for bbox %s", len(issues), bbox)
    write_json_cache(path, issues)
    return issues


def fetch_issues_for_zone(
    zone_key: str,
    *,
    force_refresh: bool = False,
    item_filter: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Fetch Osmose issues for a known MetroNow zone."""
    if zone_key not in ZONES:
        raise KeyError(f"Unknown zone {zone_key!r}; choices: {list(ZONES)}")
    bbox = tuple(ZONES[zone_key]["bbox"])
    return fetch_issues(  # type: ignore[arg-type]
        bbox,
        item_filter=item_filter,
        limit=limit,
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# Indexing + annotation
# ---------------------------------------------------------------------------

def index_issues_by_osm_id(
    issues: list[dict],
) -> dict[tuple[str, int], list[dict]]:
    """Return ``{(element_type, element_id): [issue, ...]}``.

    ``element_type`` is ``"way"``, ``"node"``, or ``"relation"``. Same
    issue can appear under multiple keys when it touches multiple elements.
    """
    out: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for issue in issues or []:
        osm_ids = issue.get("osm_ids") or {}
        for et, key in (
            ("way", "ways"),
            ("node", "nodes"),
            ("relation", "relations"),
        ):
            for eid in osm_ids.get(key) or []:
                try:
                    out[(et, int(eid))].append(issue)
                except (TypeError, ValueError):
                    continue
    return dict(out)


def annotate_fixes_with_osmose(
    fixes: list[dict],
    issues: list[dict],
) -> list[dict]:
    """Attach Osmose evidence to fixes whose target element appears in an issue.

    Mutates each fix in-place: when its ``element_id`` shows up under any
    Osmose issue, sets ``fix["osmose_match"]`` to a small descriptor and
    forces ``fix["requires_human_review"] = True`` (Osmose has already
    flagged the way; we should not auto-submit until that issue is resolved
    or confirmed unrelated). Fixes without an ``element_id``, or whose
    target isn't flagged, are left unchanged.
    """
    if not fixes or not issues:
        return fixes

    index = index_issues_by_osm_id(issues)
    if not index:
        return fixes

    for fix in fixes:
        et = fix.get("element_type") or "way"
        eid = fix.get("element_id")
        if eid is None:
            continue
        try:
            key = (str(et), int(eid))
        except (TypeError, ValueError):
            continue
        matches = index.get(key)
        if not matches:
            continue
        first = matches[0]
        fix["osmose_match"] = {
            "issue_id": first.get("id"),
            "item": first.get("item"),
            "item_title": first.get("item_title"),
            "url": first.get("url"),
            "match_count": len(matches),
        }
        fix["requires_human_review"] = True

    return fixes
