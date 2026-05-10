# Skill: `ground-truth-diff`

**Summary.** Diff OSM geometry and attributes against TIGER/Line 2024
to identify import drift, new roads, and name-field artifacts (the
"Mac Donald" / "O Toole" apostrophe-stripping bugs that survive in
TIGER residuals).

## What it does

TIGER 2024 is the public-domain fallback ground-truth: less current
and coarser-class than CAGIS, but covers every road and every county.
This skill runs `src/osm/tiger2024.py` to:

1. Fetch the TIGER 2024 county features for the zone.
2. Match each OSM way against TIGER linework via name + geometry.
3. Surface drift cases:
   - **Import drift**: OSM way has shifted from TIGER's geometry
     (real edits applied since import; usually fine, sometimes regressions).
   - **New roads**: TIGER 2024 has a road OSM doesn't.
   - **Name-field artifacts**: `Mac Donald` instead of `MacDonald`,
     `O Toole` instead of `O'Toole`, etc.; TIGER's apostrophe-stripping
     bugs preserved by the 2007-2008 import.

Fixes from TIGER are always `requires_human_review=True` because TIGER
is less current than CAGIS.

## When to invoke

- "Compare to TIGER 2024" / "Census data"
- "Find name-field artifacts"
- "Mac Donald" / "O Toole" / "import drift" / "new roads"
- Any zone-level "did anything change since import?" question.

## What it produces

- A list of drift cases, name artifacts, and missing-from-OSM roads.
- `tiger_match` annotation on relevant ways (in addition to
  `cagis_match`).
- Recommended fixes flagged as `requires_human_review=True`.

## Related skills

- [`cagis-conflate`](cagis-conflate.md): the primary ground-truth
  layer; this skill is the fallback when CAGIS has no candidate.
- [`zone-audit`](zone-audit.md): produces the OSM side of the diff.

## See also

- [`SKILL.md`](../../.claude/skills/ground-truth-diff/SKILL.md)
- [TIGER/Line 2024 boundary files](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html)
