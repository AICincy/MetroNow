"""Revision history analysis — determine whether a way has been meaningfully reviewed.

Addresses Minh Nguyen's feedback that tiger:reviewed=no is unreliable: most
mappers don't remove the tag even after fully correcting the data.  This module
analyses the actual edit history to produce a review_status and confidence score.
"""

from __future__ import annotations

from enum import Enum

from .history import batch_fetch_way_histories, extract_versions, fetch_way_history


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    LIKELY_REVIEWED = "LIKELY_REVIEWED"
    INCONCLUSIVE = "INCONCLUSIVE"


KNOWN_IMPORT_USERS = {
    "bot-mode",
    "TIGERcnl",
    "DaveHansenTiger",
    "DaveHansen-TIGER",
    "Yellowbkpk",
    "TIGER_Ohio_Mapper",
    "emacsen",
    "woodpeck_fixbot",
    "balrog-kun",
    "Sundance",
}

KNOWN_BOT_PREFIXES = ("josm", "bot-", "import", "fix", "cleanup")

TAGS_THAT_INDICATE_REVIEW = {
    "surface",
    "lanes",
    "maxspeed",
    "sidewalk",
    "cycleway",
    "lit",
    "turn:lanes",
    "turn:lanes:forward",
    "turn:lanes:backward",
    "parking:lane",
    "width",
    "foot",
    "bicycle",
    "access",
    "motor_vehicle",
    "hgv",
    "bridge",
    "tunnel",
    "layer",
    "service",
    "destination",
    "note",
}


def _is_import_user(user: str | None) -> bool:
    if not user:
        return False
    if user in KNOWN_IMPORT_USERS:
        return True
    lower = user.lower()
    return any(lower.startswith(p) for p in KNOWN_BOT_PREFIXES)


def _tier1_check(way_record: dict) -> dict | None:
    """Fast metadata check using fields from ``out meta``.

    Returns a result dict if the status is clear, or None if Tier 2 is needed.
    """
    version = way_record.get("version")
    user = way_record.get("user")

    if version == 1:
        return {
            "review_status": ReviewStatus.UNREVIEWED,
            "review_confidence": 0.95,
            "review_reason": "Version 1 — never edited since import",
        }

    if version is not None and version >= 2 and not _is_import_user(user):
        confidence = min(0.6 + (version - 2) * 0.05, 0.85)
        return {
            "review_status": ReviewStatus.LIKELY_REVIEWED,
            "review_confidence": confidence,
            "review_reason": f"Version {version}, last editor '{user}' is not an import bot",
        }

    return None


def _tier2_analyse(way_record: dict, history_data: dict | None) -> dict:
    """Complete analysis given fetched history data."""
    if way_record.get("id") is None:
        return {
            "review_status": ReviewStatus.INCONCLUSIVE,
            "review_confidence": 0.0,
            "review_reason": "No way ID available",
        }

    if history_data is None:
        return {
            "review_status": ReviewStatus.INCONCLUSIVE,
            "review_confidence": 0.3,
            "review_reason": "Could not fetch history from OSM API",
        }

    versions = extract_versions(history_data, "way")
    if not versions:
        return {
            "review_status": ReviewStatus.INCONCLUSIVE,
            "review_confidence": 0.3,
            "review_reason": "Empty history response",
        }

    human_edits = []
    import_version_tags: dict | None = None
    for v in versions:
        if v["version"] == 1:
            import_version_tags = v.get("tags", {})
        if not _is_import_user(v.get("user")):
            human_edits.append(v)

    if not human_edits:
        return {
            "review_status": ReviewStatus.UNREVIEWED,
            "review_confidence": 0.9,
            "review_reason": "All edits by import bots — no human editor has touched this way",
        }

    meaningful_changes = _check_meaningful_changes(
        versions, import_version_tags or {}
    )

    if meaningful_changes:
        return {
            "review_status": ReviewStatus.LIKELY_REVIEWED,
            "review_confidence": 0.75,
            "review_reason": meaningful_changes,
        }

    return {
        "review_status": ReviewStatus.INCONCLUSIVE,
        "review_confidence": 0.5,
        "review_reason": (
            f"Edited by {len(human_edits)} human editor(s) but no "
            f"meaningful tag or geometry changes detected"
        ),
    }


def analyse_way_history(way_record: dict) -> dict:
    """Analyse a single way's edit history and assign a review status.

    Tier 1: fast check using metadata already present from ``out meta``.
    Tier 2: if ambiguous, fetch full history from OSM API and inspect
    what changed between versions.

    Returns a dict with review_status, review_confidence, and review_reason.
    """
    result = _tier1_check(way_record)
    if result is not None:
        return result

    history_data = fetch_way_history(way_record.get("id"))
    return _tier2_analyse(way_record, history_data)


def _is_tiger_tag(key: str) -> bool:
    return key.startswith("tiger:") or key in ("source", "source:name")


def _only_tiger_tags_changed(prev_tags: dict, curr_tags: dict) -> bool:
    """Return True if all differences between two tag sets are tiger:* or source tags."""
    all_keys = set(prev_tags.keys()) | set(curr_tags.keys())
    for k in all_keys:
        if prev_tags.get(k) != curr_tags.get(k) and not _is_tiger_tag(k):
            return False
    return True


def _check_meaningful_changes(
    versions: list[dict], import_tags: dict
) -> str | None:
    """Check whether any version introduced meaningful changes to the way.

    Returns a reason string if meaningful changes found, else None.
    Edits that only add/remove tiger:* or source tags are not meaningful.
    """
    if len(versions) < 2:
        return None

    for i in range(1, len(versions)):
        prev = versions[i - 1]
        curr = versions[i]
        if _is_import_user(curr.get("user")):
            continue

        prev_tags = prev.get("tags", {})
        curr_tags = curr.get("tags", {})

        if _only_tiger_tags_changed(prev_tags, curr_tags) and prev.get("nodes") == curr.get("nodes"):
            continue

        added_tags = set(curr_tags.keys()) - set(prev_tags.keys())
        non_tiger_added = {t for t in added_tags if not _is_tiger_tag(t)}
        review_tags_added = non_tiger_added & TAGS_THAT_INDICATE_REVIEW
        if review_tags_added:
            return (
                f"Version {curr['version']} by '{curr.get('user')}' added "
                f"review-indicating tags: {', '.join(sorted(review_tags_added))}"
            )

        for tag in ("oneway", "highway", "name", "junction", "access"):
            if prev_tags.get(tag) != curr_tags.get(tag):
                old_val = prev_tags.get(tag, "(absent)")
                new_val = curr_tags.get(tag, "(removed)")
                return (
                    f"Version {curr['version']} by '{curr.get('user')}' changed "
                    f"'{tag}': {old_val} → {new_val}"
                )

        prev_nodes = prev.get("nodes", [])
        curr_nodes = curr.get("nodes", [])
        if prev_nodes != curr_nodes:
            added_nodes = len(set(curr_nodes) - set(prev_nodes))
            removed_nodes = len(set(prev_nodes) - set(curr_nodes))
            if added_nodes or removed_nodes:
                return (
                    f"Version {curr['version']} by '{curr.get('user')}' modified "
                    f"way geometry (+{added_nodes}/-{removed_nodes} nodes)"
                )

    return None


def filter_by_history(
    all_ways: list[dict],
    *,
    skip_history: bool = False,
    progress_callback=None,
    max_concurrent: int = 10,
) -> list[dict]:
    """Annotate each way with review_status and filter to actionable ways.

    If skip_history is True, all ways pass through (legacy tiger:reviewed=no mode).
    Otherwise uses a two-pass strategy: Tier 1 metadata checks first, then
    batch-fetches histories for ambiguous ways concurrently via httpx.
    """
    total = len(all_ways)

    if skip_history:
        for i, w in enumerate(all_ways):
            w["review_status"] = ReviewStatus.UNREVIEWED.value
            w["review_confidence"] = 0.0
            w["review_reason"] = "History analysis skipped (legacy mode)"
            if progress_callback:
                progress_callback(i + 1, total)
        return all_ways

    # Pass 1: Tier 1 fast checks — no HTTP calls
    tier2_ways: list[dict] = []
    for w in all_ways:
        result = _tier1_check(w)
        if result is not None:
            w["review_status"] = result["review_status"].value
            w["review_confidence"] = result["review_confidence"]
            w["review_reason"] = result["review_reason"]
        else:
            tier2_ways.append(w)

    tier1_done = total - len(tier2_ways)
    if progress_callback:
        progress_callback(tier1_done, total)

    # Pass 2: batch fetch histories for Tier 2 ways concurrently
    if tier2_ways:
        way_ids = [w["id"] for w in tier2_ways if w.get("id") is not None]
        histories = batch_fetch_way_histories(way_ids, max_concurrent=max_concurrent)

        for i, w in enumerate(tier2_ways):
            history_data = histories.get(w.get("id"))
            result = _tier2_analyse(w, history_data)
            w["review_status"] = result["review_status"].value
            w["review_confidence"] = result["review_confidence"]
            w["review_reason"] = result["review_reason"]
            if progress_callback:
                progress_callback(tier1_done + i + 1, total)

    return all_ways
