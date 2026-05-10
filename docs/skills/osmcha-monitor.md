# Skill: `osmcha-monitor`

**Summary.** Set up and query OSMCha monitoring for the
`_cincyimport` account's MetroNow zone changesets. Two modes:
**post-submission** monitoring via the OSMCha REST API, and
**pre-submission** scoring via the local `osmcha` Python package on a
proposed-edit JSON.

## What it does

[OSMCha](https://osmcha.org) is the OSM community's changeset-review
tool — DWG and reviewers use it to spot bad edits. This skill:

- Sets up an OSMCha filter scoped to the `_cincyimport` account inside
  the four MetroNow zone polygons. The filter URL becomes the project's
  monitoring dashboard.
- Queries OSMCha for recent changesets matching the filter, surfacing
  any flagged-for-review or reverted edits within 72 hours of the first
  submission window.
- Optionally pre-scores a proposed changeset locally via the `osmcha`
  Python package's heuristic engine — same scoring OSMCha runs server-
  side, but on a JSON before submission.

## When to invoke

- "Monitor edits" / "check OSMCha" / "watch the account"
- "Score this changeset" (pre-submission)
- "Did anything get reverted?"
- Day-of and 72-hour-post checks on first submission.

## What it produces

- A configured OSMCha filter URL.
- A list of recent changesets for the account/zones with status,
  flagged-status, and reviewer comments.
- (Pre-submission mode) A heuristic-score breakdown for a proposed
  changeset.

## Related skills

- [`changeset-submit`](changeset-submit.md) — submitting; this skill is
  the post-submission watchdog.
- [`tiger-history-deep`](tiger-history-deep.md) — pre-submission
  per-way verification.

## See also

- [`SKILL.md`](../../.claude/skills/osmcha-monitor/SKILL.md)
- [`docs/explainers/preflight-checks.md`](../explainers/preflight-checks.md)
  — `check_osmcha_subscription` is in `CAT_MONITORING`.
- [OSMCha](https://osmcha.org/)
