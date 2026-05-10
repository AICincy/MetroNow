# Skill: `zone-audit`

**Summary.** Run the full TIGER defect audit pipeline for one MetroNow
service zone: Overpass fetch → classify defects → history filter →
generate XLSX/CSV/dashboard reports. The end-to-end audit is the
project's primary "do a scan" workflow.

## What it does

Walks one zone through every pipeline stage in `src/osm/`:

1. `fetch.py`: Overpass query bounded by the zone bbox, with retry +
   mirror fallback.
2. `polygons.py`: clip to the real zone polygon (centroid containment).
3. `classify.py`: assign defect classes (A / AB / B / C) plus
   node-disconnect gaps.
4. `history_filter.py`: analyse revision history to label each way
   UNREVIEWED / LIKELY_REVIEWED / INCONCLUSIVE.
5. Reports: XLSX workbook (8 sheets), interactive Leaflet dashboard,
   four CSV slices.

Defect class definitions:

- **Class AB** (Critical): `highway=residential` + truthy `oneway` +
  multi-segment shared name. Compound defect, highest routing impact.
- **Class A** (Critical): false `oneway=yes` on residential streets.
- **Class B** (High): 2+ ways sharing a normalized name with
  disconnect risk.
- **Class C** (Low): unreviewed, no immediate defect signal.

## When to invoke

- "Run a scan / audit on `<zone>`"
- "Check `blue-ash-montgomery`"
- Mention of any of the four zone keys (`blue-ash-montgomery`,
  `springdale-sharonville`, `northgate-mt-healthy`,
  `forest-park-pleasant-run`).
- Any phrase like "the audit pipeline" or "the full pipeline."

## What it produces

Under `osm-audit-<zone>/`:

- `data/`: raw Overpass cache (gitignored)
- `scan-results.json`: combined classifier + detector outputs
- `reports/`: XLSX workbook (8 sheets)
- `reports/dashboard.html`: Leaflet visualization
- `csv/`: four CSV slices (by class)

## Related skills

- [`cagis-conflate`](cagis-conflate.md): runs *after* the scan to
  ground-truth the classifier output.
- [`tiger-history-deep`](tiger-history-deep.md): drill into one
  specific way's history when the zone audit's bulk
  `LIKELY_REVIEWED` / `INCONCLUSIVE` label needs verification.
- [`ground-truth-diff`](ground-truth-diff.md): TIGER/Line 2024
  comparison; complements the CAGIS conflation.
- [`maproulette-challenge`](maproulette-challenge.md): turn the
  unverified Class A/AB output into community-review tasks.

## See also

- [`SKILL.md`](../../.claude/skills/zone-audit/SKILL.md): canonical
  source, including argument-hint and pipeline-step rationale.
- [`docs/explainers/detector-taxonomy.md`](../explainers/detector-taxonomy.md)
- [`docs/explainers/zone-data-flow.md`](../explainers/zone-data-flow.md)
