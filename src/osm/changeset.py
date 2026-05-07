"""OSM API changeset creation and submission."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET

import requests

from .auth import get_access_token
from .config import OSM_API_BASE

log = logging.getLogger(__name__)


def _auth_headers() -> dict:
    token = get_access_token()
    if not token:
        raise RuntimeError(
            "Not authenticated. Run 'osm auth login' first."
        )
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "osm-audit-pipeline/0.1 (Hamilton County TIGER defect audit)",
    }


CHANGESET_BATCH_SIZE = 500

DEFAULT_SOURCE = "survey;CAGIS Open Data Hub;ODOT TIMS"
DEFAULT_WIKI_URL = ""


def create_changeset(
    comment: str,
    source: str = DEFAULT_SOURCE,
    wiki_url: str = DEFAULT_WIKI_URL,
    mechanical: bool = True,
) -> int:
    """Open a new changeset on OSM. Returns the changeset ID."""
    headers = _auth_headers()
    headers["Content-Type"] = "text/xml"

    tags = [
        f'<tag k="comment" v="{_xml_escape(comment)}"/>',
        f'<tag k="source" v="{_xml_escape(source)}"/>',
        '<tag k="created_by" v="MetroNow TIGER Audit Pipeline/0.1"/>',
    ]
    if mechanical:
        tags.append('<tag k="mechanical" v="yes"/>')
        tags.append('<tag k="bot" v="yes"/>')
    if wiki_url:
        tags.append(f'<tag k="description" v="{_xml_escape(wiki_url)}"/>')

    changeset_xml = "<osm><changeset>" + "".join(tags) + "</changeset></osm>"

    resp = requests.put(
        f"{OSM_API_BASE}/changeset/create",
        data=changeset_xml,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return int(resp.text.strip())


def close_changeset(changeset_id: int) -> None:
    """Close an open changeset."""
    headers = _auth_headers()
    resp = requests.put(
        f"{OSM_API_BASE}/changeset/{changeset_id}/close",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()


def fetch_current_way(way_id: int) -> ET.Element:
    """Fetch the current version of a way from the OSM API as XML."""
    resp = requests.get(
        f"{OSM_API_BASE}/way/{way_id}",
        headers={
            "User-Agent": "osm-audit-pipeline/0.1",
            "Accept": "application/xml",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return ET.fromstring(resp.text)


def apply_tag_changes(way_xml: ET.Element, changeset_id: int, changes: dict) -> str:
    """Apply tag changes to a way XML element and prepare for upload.

    changes is a dict of {tag_key: new_value}. A value of None removes the tag.
    """
    way_el = way_xml.find("way")
    if way_el is None:
        raise ValueError("No <way> element found in response")

    way_el.set("changeset", str(changeset_id))

    for key, value in changes.items():
        existing = None
        for tag in way_el.findall("tag"):
            if tag.get("k") == key:
                existing = tag
                break
        if value is None:
            if existing is not None:
                way_el.remove(existing)
        elif existing is not None:
            existing.set("v", str(value))
        else:
            new_tag = ET.SubElement(way_el, "tag")
            new_tag.set("k", key)
            new_tag.set("v", str(value))

    return ET.tostring(way_xml, encoding="unicode")


def upload_way(changeset_id: int, way_id: int, way_xml_str: str) -> int:
    """Upload a modified way to an open changeset. Returns the new version number."""
    headers = _auth_headers()
    headers["Content-Type"] = "text/xml"

    resp = requests.put(
        f"{OSM_API_BASE}/way/{way_id}",
        data=way_xml_str,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return int(resp.text.strip())


def _resolve_changes(fix: dict) -> dict:
    """Extract the tag changes dict from a fix descriptor."""
    if fix["action"] == "remove_tag":
        return {fix["tag"]: None}
    if fix["action"] == "modify_tag":
        return fix.get("changes", {})
    raise ValueError(f"Unknown action: {fix['action']}")


def _build_osmchange(fixes: list[dict], changeset_id: int) -> tuple[str, list[str]]:
    """Fetch current state of each way, apply changes, and build an osmChange XML.

    Returns (osmchange_xml_string, list_of_error_messages).
    Uses one GET per way but a single diff upload for the whole batch.
    """
    root = ET.Element("osmChange")
    modify = ET.SubElement(root, "modify")
    errors: list[str] = []

    for i, fix in enumerate(fixes):
        way_id = fix["element_id"]
        try:
            if i > 0:
                time.sleep(0.5)
            changes = _resolve_changes(fix)
            way_xml = fetch_current_way(way_id)
            way_el = way_xml.find("way")
            if way_el is None:
                raise ValueError("No <way> element in API response")

            way_el.set("changeset", str(changeset_id))

            for key, value in changes.items():
                existing = None
                for tag in way_el.findall("tag"):
                    if tag.get("k") == key:
                        existing = tag
                        break
                if value is None:
                    if existing is not None:
                        way_el.remove(existing)
                elif existing is not None:
                    existing.set("v", str(value))
                else:
                    new_tag = ET.SubElement(way_el, "tag")
                    new_tag.set("k", key)
                    new_tag.set("v", str(value))

            modify.append(way_el)
        except Exception as exc:
            msg = f"Way {way_id}: {exc}"
            errors.append(msg)
            log.warning("Skipping fix: %s", msg)

    return ET.tostring(root, encoding="unicode"), errors


def upload_diff(changeset_id: int, osmchange_xml: str) -> None:
    """Upload an osmChange document to a changeset via diff upload."""
    headers = _auth_headers()
    headers["Content-Type"] = "text/xml"
    resp = requests.post(
        f"{OSM_API_BASE}/changeset/{changeset_id}/upload",
        data=osmchange_xml,
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()


def submit_fixes(
    accepted_fixes: list[dict],
    comment: str = "TIGER defect correction in MetroNow zone",
    *,
    dry_run: bool = False,
    source: str = DEFAULT_SOURCE,
    wiki_url: str = DEFAULT_WIKI_URL,
    batch_size: int = CHANGESET_BATCH_SIZE,
) -> dict:
    """Submit accepted fixes as batched OSM changesets.

    Splits fixes into batches of batch_size (default 500, community norm).
    Returns a summary dict with changeset_ids, fixes_applied, and errors.
    """
    if not accepted_fixes:
        return {"changeset_ids": [], "fixes_applied": 0, "errors": []}

    if dry_run:
        log.info("[DRY RUN] Would submit %d fix(es)", len(accepted_fixes))
        for fix in accepted_fixes:
            log.info("  - %s", fix["description"])
        batches = (len(accepted_fixes) + batch_size - 1) // batch_size
        log.info("  (%d changeset(s) of up to %d elements each)", batches, batch_size)
        return {
            "changeset_ids": [],
            "fixes_applied": len(accepted_fixes),
            "errors": [],
            "dry_run": True,
        }

    changeset_ids: list[int] = []
    total_applied = 0
    all_errors: list[str] = []

    for batch_start in range(0, len(accepted_fixes), batch_size):
        batch = accepted_fixes[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(accepted_fixes) + batch_size - 1) // batch_size
        batch_comment = comment
        if total_batches > 1:
            batch_comment = f"{comment} (batch {batch_num}/{total_batches})"

        changeset_id = create_changeset(
            batch_comment, source=source, wiki_url=wiki_url
        )
        changeset_ids.append(changeset_id)
        log.info(
            "Opened changeset %d (batch %d/%d, %d fixes)",
            changeset_id, batch_num, total_batches, len(batch),
        )

        osmchange_xml, fetch_errors = _build_osmchange(batch, changeset_id)
        all_errors.extend(fetch_errors)

        applied = len(batch) - len(fetch_errors)
        if applied > 0:
            try:
                upload_diff(changeset_id, osmchange_xml)
            except Exception as exc:
                msg = f"Diff upload for changeset {changeset_id}: {exc}"
                all_errors.append(msg)
                log.error("Diff upload failed: %s", msg)
                applied = 0

        close_changeset(changeset_id)
        if applied == 0:
            log.warning("Changeset %d closed empty — all fixes in batch errored", changeset_id)
        total_applied += applied
        log.info(
            "Closed changeset %d: %d fix(es) — https://www.openstreetmap.org/changeset/%d",
            changeset_id, applied, changeset_id,
        )

    if all_errors:
        log.warning("%d error(s) total across all batches", len(all_errors))

    return {
        "changeset_ids": changeset_ids,
        "fixes_applied": total_applied,
        "errors": all_errors,
    }


def _xml_escape(text: str) -> str:
    from xml.sax.saxutils import escape, quoteattr
    return escape(text, {'"': "&quot;", "'": "&apos;"})
