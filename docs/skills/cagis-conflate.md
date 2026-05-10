# Skill: `cagis-conflate`

**Summary.** Cross-reference the audit pipeline's classified ways
against authoritative ground-truth: CAGIS quarterly road centerlines
(primary) and the aspirational ODOT TIMS feed (placeholder). Produces
the `cagis_match` annotation that gates the auto-submit pool.

## What it does

Runs `osm.conflate.conflate()` against a scan's `all_ways`:

1. Load CAGIS centerlines for the zone (90-day cache at
   `~/.config/osm/cagis_cache/`).
2. Build a Shapely STRtree spatial index over the centerlines.
3. For each OSM way, score the best in-buffer (30m) candidate via
   directed Hausdorff + name similarity + direction alignment.
4. Cap fallback (100m) matches at `REVIEW_CONFIDENCE` (0.6) so they
   never auto-submit.
5. Attach a `cagis_match` dict to each way (or `None`).

The conflation matcher is the *epistemic gate* of the project: only
ways with `confidence ≥ HIGH_CONFIDENCE` (0.85) become eligible for
mechanical auto-submission.

## When to invoke

- "Cross-reference CAGIS"
- "Validate this classification against ground truth"
- "Run conflation on `<zone>`"
- Mention of CAGIS, ODOT TIMS, "centerlines," "ground truth"
- A specific way ID with "is this real?" framing: the skill loads
  CAGIS for the zone and reports the match.

## What it produces

- Mutated `scan-results.json` with `cagis_match` annotations on every
  `all_ways` entry.
- (Optional) A baseline manifest at
  `osm-audit-<zone>/data/cagis_baseline_*.json` for asymmetric-promotion
  tracking via `osm baseline-diff`.
- A summary line: "matched N / M OSM ways."

## Related skills

- [`zone-audit`](zone-audit.md): produces the input `scan-results.json`
  this skill annotates.
- [`ground-truth-diff`](ground-truth-diff.md): TIGER 2024 fallback
  ground-truth when CAGIS has no candidate.
- [`changeset-submit`](changeset-submit.md): only consumes ways whose
  `cagis_match.confidence ≥ 0.85`.

## See also

- [`SKILL.md`](../../.claude/skills/cagis-conflate/SKILL.md)
- [`docs/explainers/conflation-matcher.md`](../explainers/conflation-matcher.md)
- [CAGIS Open Data Hub](https://cagisonline.hamilton-co.org/cagisonline/)
