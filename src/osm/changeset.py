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


def create_changeset(comment: str, source: str = "survey") -> int:
    """Open a new changeset on OSM. Returns the changeset ID."""
    headers = _auth_headers()
    headers["Content-Type"] = "text/xml"

    changeset_xml = (
        '<osm>'
        '<changeset>'
        f'<tag k="comment" v="{_xml_escape(comment)}"/>'
        f'<tag k="source" v="{_xml_escape(source)}"/>'
        '<tag k="created_by" v="osm-audit-pipeline/0.1"/>'
        '</changeset>'
        '</osm>'
    )

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


def apply_tag_removal(way_xml: ET.Element, changeset_id: int, tag_key: str) -> str:
    """Remove a tag from a way XML element and prepare for upload."""
    way_el = way_xml.find("way")
    if way_el is None:
        raise ValueError("No <way> element found in response")

    way_el.set("changeset", str(changeset_id))

    for tag in way_el.findall("tag"):
        if tag.get("k") == tag_key:
            way_el.remove(tag)
            break

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


def submit_fixes(
    accepted_fixes: list[dict],
    comment: str = "Remove false oneway=yes tags on residential streets (TIGER audit)",
    *,
    dry_run: bool = False,
) -> dict:
    """Submit accepted fixes as a single OSM changeset.

    Returns a summary dict with changeset_id, fixes_applied, and any errors.
    """
    if not accepted_fixes:
        return {"changeset_id": None, "fixes_applied": 0, "errors": []}

    if dry_run:
        print(f"\n[DRY RUN] Would submit {len(accepted_fixes)} fix(es):")
        for fix in accepted_fixes:
            print(f"  - {fix['description']}")
        return {"changeset_id": None, "fixes_applied": len(accepted_fixes), "errors": [], "dry_run": True}

    changeset_id = create_changeset(comment)
    print(f"Opened changeset {changeset_id}")

    applied = 0
    errors: list[str] = []

    for fix in accepted_fixes:
        try:
            if fix["action"] == "remove_tag":
                way_xml = fetch_current_way(fix["element_id"])
                modified = apply_tag_removal(way_xml, changeset_id, fix["tag"])
                new_version = upload_way(changeset_id, fix["element_id"], modified)
                print(f"  Fixed way {fix['element_id']} → v{new_version}")
                applied += 1
            else:
                errors.append(f"Unknown action: {fix['action']}")
        except Exception as exc:
            errors.append(f"Way {fix.get('element_id', '?')}: {exc}")
            print(f"  ERROR on way {fix.get('element_id', '?')}: {exc}")

    close_changeset(changeset_id)
    print(f"Closed changeset {changeset_id}: {applied} fix(es) applied")
    if errors:
        print(f"  {len(errors)} error(s) encountered")

    return {
        "changeset_id": changeset_id,
        "fixes_applied": applied,
        "errors": errors,
    }


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
