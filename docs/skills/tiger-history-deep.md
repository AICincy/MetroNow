# Skill: `tiger-history-deep`

**Summary.** Deep revision-history analysis for one specific OSM way —
fetch the full version history from OSM API v0.6, identify which edits
were import bots vs. humans, classify the way's review status with a
confidence score and a human-readable reason.

## What it does

Where `history-filter.py` operates in bulk over a scan's `all_ways`,
this skill drills into ONE way:

1. Fetch full revision history (`history.fetch_way_history`).
2. Walk every version's editor + tags + geometry change.
3. Classify against `KNOWN_IMPORT_USERS` + `KNOWN_BOT_PREFIXES` +
   `TAGS_THAT_INDICATE_REVIEW`.
4. Return UNREVIEWED / LIKELY_REVIEWED / INCONCLUSIVE with
   confidence (0.0–0.95) and a one-sentence rationale.

Useful when the bulk audit has labeled a way INCONCLUSIVE and you need
to decide: was this a TIGER residual, or has someone actually looked
at it?

## When to invoke

- A specific way ID is mentioned (e.g. "what about way 12345678?").
- "Edit history" / "version history" of a way.
- "Was way X reviewed?"
- INCONCLUSIVE status appears in a scan result and the user wants to
  resolve it.

## What it produces

- A per-way report with:
  - `review_status` (UNREVIEWED / LIKELY_REVIEWED / INCONCLUSIVE)
  - `review_confidence` (0.0–0.95)
  - `review_reason` (human-readable)
  - Version-by-version breakdown of edits
  - Identified import bots vs. human editors

## Related skills

- [`zone-audit`](zone-audit.md) — runs `history_filter` in bulk; this
  skill is the single-way drill-down.
- [`osmcha-monitor`](osmcha-monitor.md) — for *post*-submission edit
  monitoring; this skill is for pre-submission diligence.

## See also

- [`SKILL.md`](../../.claude/skills/tiger-history-deep/SKILL.md)
- [`docs/explainers/history-filter.md`](../explainers/history-filter.md)
  — the bulk-mode counterpart this skill complements.
