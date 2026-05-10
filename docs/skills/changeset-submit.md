# Skill: `changeset-submit`

**Summary.** Submit corrections to the OSM API v0.6 with full community
compliance — proper changeset tags (mechanical=yes, bot=yes,
description, cagis:attribution), size limits (≤500 elements per
community norm, hard cap 10,000), rate-limit awareness, and
`--dry-run` support that prints the exact changeset XML without
posting.

## What it does

Drives `osm.changeset.submit_fixes()`:

1. Verify pre-flight — `osm preflight --zone <key>` must be clean
   (skill refuses to submit on FAIL; warns on WARN unless `--strict`).
2. Open a new changeset with the seven canonical tags from
   `changeset.py:98-111` (comment, source, created_by,
   mechanical=yes, bot=yes, description=`WIKI_URL`,
   cagis:attribution).
3. Build an `osmChange` XML with one `<modify>` block per fix,
   capped at the requested batch size.
4. Upload via the OSM API; on success, close the changeset and
   record the changeset ID + URL.
5. On `--dry-run`, stop after step 3 and print the XML.

First-batch convention: 10 elements. Watch OSMCha for 72 hours, then
scale gradually toward the ~500-element community norm.

## When to invoke

- "Submit" / "push corrections" / "fix" / "create changeset"
- "Apply corrections to OpenStreetMap"
- "Dry run" — explicit no-network invocation
- After Phase 1 community gating is complete (per `community-prep`).

## What it produces

- (Live mode) A submitted changeset on osm.org, with ID + URL printed.
  Changeset includes seven tags + the fix payload.
- (Dry-run mode) The full `osmChange` XML printed to stdout for
  human inspection.
- (Either mode) An `osmcha-monitor`-ready filter URL for post-submission
  watch.

## Related skills

- [`community-prep`](community-prep.md) — must be complete before this
  skill submits.
- [`cagis-conflate`](cagis-conflate.md) — only ways with
  `cagis_match.confidence ≥ 0.85` are eligible for this skill's queue.
- [`osmcha-monitor`](osmcha-monitor.md) — the post-submission watchdog.

## See also

- [`SKILL.md`](../../.claude/skills/changeset-submit/SKILL.md)
- [`docs/explainers/osm-community-gating.md`](../explainers/osm-community-gating.md)
  — the seven changeset tags and what each does.
- [`docs/explainers/preflight-checks.md`](../explainers/preflight-checks.md)
  — the gate this skill respects.
