"""Unit tests for src/osm/changeset.py.

Closes the coverage gap flagged in the 2026-05-10 tests/ compliance
audit: changeset.py was holding the CAGIS-attribution tag (a hard
requirement of the Open Data Hub license) with no direct test. A
regression in `_has_cagis_evidence()` or in the `cagis_verified`
tag-emission branch of `create_changeset()` would silently strip
required attribution from every submitted changeset.

These tests stay offline. Network paths through `requests.put/get`
are mocked; only the pure-Python branches (evidence detection,
XML-escape, tag composition) are exercised directly.
"""

from __future__ import annotations

import pytest

from osm import changeset as cs


# ---------------------------------------------------------------------------
# _has_cagis_evidence
# ---------------------------------------------------------------------------

def test_has_cagis_evidence_true_when_any_fix_has_cagis_id():
    fixes = [
        {"source_evidence": {"tiger_id": "1234"}},
        {"source_evidence": {"cagis_id": "RAMP-7"}},
    ]
    assert cs._has_cagis_evidence(fixes) is True


def test_has_cagis_evidence_false_when_no_cagis_id():
    fixes = [
        {"source_evidence": {"tiger_id": "1234"}},
        {"source_evidence": {"odot_id": "X"}},
    ]
    assert cs._has_cagis_evidence(fixes) is False


def test_has_cagis_evidence_false_when_evidence_missing():
    assert cs._has_cagis_evidence([{}]) is False
    assert cs._has_cagis_evidence([]) is False


def test_has_cagis_evidence_ignores_non_dict_evidence():
    fixes = [{"source_evidence": "cagis_id=42"}, {"source_evidence": None}]
    assert cs._has_cagis_evidence(fixes) is False


def test_has_cagis_evidence_treats_explicit_none_cagis_id_as_absent():
    fixes = [{"source_evidence": {"cagis_id": None}}]
    assert cs._has_cagis_evidence(fixes) is False


# ---------------------------------------------------------------------------
# _xml_escape
# ---------------------------------------------------------------------------

def test_xml_escape_handles_ampersand_and_quotes():
    out = cs._xml_escape('Smith & Sons "Co." <pickup>')
    assert out == 'Smith &amp; Sons &quot;Co.&quot; &lt;pickup&gt;'


def test_xml_escape_handles_apostrophe():
    # The escape table passed to xml.sax.saxutils.escape() includes
    # ' → &apos;, so the OAuth changeset comment for "O'Toole Avenue"
    # corrections renders safely even though the OSM way name carries
    # a literal apostrophe.
    assert cs._xml_escape("O'Toole") == "O&apos;Toole"


def test_xml_escape_preserves_safe_text():
    safe = "CAGIS Open Data Hub - Hamilton County, Ohio"
    assert cs._xml_escape(safe) == safe


# ---------------------------------------------------------------------------
# create_changeset — tag composition under cagis_verified
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def captured_put(monkeypatch):
    """Capture the XML body that create_changeset would PUT to OSM."""
    sent: dict = {}

    def _fake_put(url, data, headers, timeout):
        sent["url"] = url
        sent["data"] = data
        sent["headers"] = headers
        return _FakeResp("42")

    monkeypatch.setattr(cs.requests, "put", _fake_put)
    monkeypatch.setattr(cs, "_auth_headers", lambda: {"Authorization": "Bearer test"})
    return sent


def test_create_changeset_omits_cagis_tag_when_unverified(captured_put):
    cs_id = cs.create_changeset(
        comment="audit fix",
        wiki_url="",
        cagis_verified=False,
    )
    assert cs_id == 42
    assert "cagis:attribution" not in captured_put["data"]


def test_create_changeset_emits_cagis_tag_when_verified(captured_put):
    cs.create_changeset(
        comment="audit fix",
        wiki_url="",
        cagis_verified=True,
    )
    # The cagis:attribution tag must carry the exact licensed
    # attribution string, properly XML-escaped, in its v="..."
    # attribute. Partial-match assertions would let a regression
    # to a wrong attribution slip through.
    assert (
        f'k="cagis:attribution" v="{cs._xml_escape(cs.CAGIS_ATTRIBUTION)}"'
        in captured_put["data"]
    )


def test_create_changeset_emits_mechanical_and_bot_tags_by_default(captured_put):
    cs.create_changeset(comment="x", wiki_url="")
    body = captured_put["data"]
    assert 'k="mechanical" v="yes"' in body
    assert 'k="bot" v="yes"' in body


def test_create_changeset_omits_mechanical_tags_when_disabled(captured_put):
    cs.create_changeset(comment="x", wiki_url="", mechanical=False)
    body = captured_put["data"]
    assert 'k="mechanical"' not in body
    assert 'k="bot"' not in body


def test_create_changeset_includes_description_when_wiki_url_set(captured_put):
    cs.create_changeset(comment="x", wiki_url="https://wiki.example/page")
    assert 'k="description" v="https://wiki.example/page"' in captured_put["data"]


def test_create_changeset_escapes_user_supplied_comment(captured_put):
    cs.create_changeset(comment='evil "<script>"', wiki_url="")
    # The comment must be XML-escaped, never embedded raw
    assert "<script>" not in captured_put["data"]
    assert "&lt;script&gt;" in captured_put["data"]


def test_create_changeset_default_source_is_survey_and_cagis(captured_put):
    cs.create_changeset(comment="x", wiki_url="")
    assert 'k="source" v="survey;CAGIS Open Data Hub"' in captured_put["data"]


# ---------------------------------------------------------------------------
# create_changeset — request shape
# ---------------------------------------------------------------------------

def test_create_changeset_targets_osm_api_changeset_create(captured_put):
    cs.create_changeset(comment="x", wiki_url="")
    assert captured_put["url"].endswith("/changeset/create")


def test_create_changeset_sends_xml_content_type(captured_put):
    cs.create_changeset(comment="x", wiki_url="")
    assert captured_put["headers"]["Content-Type"] == "text/xml"


# ---------------------------------------------------------------------------
# Module-level constants are stable (regression guard)
# ---------------------------------------------------------------------------

def test_default_source_value():
    assert cs.DEFAULT_SOURCE == "survey;CAGIS Open Data Hub"


def test_cagis_attribution_mentions_cagis_open_data_hub_and_license():
    # Open Data Hub licensing requires explicit attribution + license stance
    assert "CAGIS Open Data Hub" in cs.CAGIS_ATTRIBUTION
    assert "license" in cs.CAGIS_ATTRIBUTION.lower()


def test_changeset_batch_size_is_under_cgimap_limit():
    # CGImap hard limit is 10,000 elements per changeset; community norm ~500.
    # The project default must stay under the hard limit.
    assert cs.CHANGESET_BATCH_SIZE <= 10000
    assert cs.CHANGESET_BATCH_SIZE >= 1
