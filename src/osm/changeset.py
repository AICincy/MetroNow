"""OSM API changeset creation and submission."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from .auth import get_access_token
from .config import OSM_API_BASE


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


def _apply_single_fix(fix: dict, changeset_id: int) -> None:
    """Apply one fix to an open changeset."""
    changes = fix.get("changes", {})
    if fix["action"] == "remove_tag":
        changes = {fix["tag"]: None}
    elif fix["action"] == "modify_tag":
        pass
    else:
        raise ValueError(f"Unknown action: {fix['action']}")

    way_xml = fetch_current_way(fix["element_id"])
    modified = apply_tag_changes(way_xml, changeset_id, changes)
    new_version = upload_way(changeset_id, fix["element_id"], modified)
    print(f"  Fixed way {fix['element_id']} → v{new_version}")


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
        print(f"\n[DRY RUN] Would submit {len(accepted_fixes)} fix(es):")
        for fix in accepted_fixes:
            print(f"  - {fix['description']}")
        batches = (len(accepted_fixes) + batch_size - 1) // batch_size
        print(f"  ({batches} changeset(s) of up to {batch_size} elements each)")
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
        print(f"Opened changeset {changeset_id} (batch {batch_num}/{total_batches}, {len(batch)} fixes)")

        applied = 0
        for fix in batch:
            try:
                _apply_single_fix(fix, changeset_id)
                applied += 1
            except Exception as exc:
                msg = f"Way {fix.get('element_id', '?')}: {exc}"
                all_errors.append(msg)
                print(f"  ERROR: {msg}")

        close_changeset(changeset_id)
        total_applied += applied
        url = f"https://www.openstreetmap.org/changeset/{changeset_id}"
        print(f"Closed changeset {changeset_id}: {applied} fix(es) — {url}")

    if all_errors:
        print(f"\n{len(all_errors)} error(s) total across all batches")

    return {
        "changeset_ids": changeset_ids,
        "fixes_applied": total_applied,
        "errors": all_errors,
    }


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
