# Skill: `maproulette-challenge`

**Summary.** Generate a MapRoulette challenge from a scan's results
for defect classes whose expected false-positive rate exceeds 5%.
Creates a per-zone GeoJSON Lines file (one task per OSM way) with
the way's polyline, a Markdown instruction explaining the suspicion,
and CAGIS evidence (when available) so community mappers can verify
or dismiss each finding.

## What it does

Wraps `osm.maproulette`:

1. Filter classified ways via `unverified_class_a_ways()`: keeps
   Class A/AB ways whose `cagis_match.confidence < 0.85` (so they
   don't duplicate the auto-submit pool).
2. Generate per-task Markdown instruction with three CAGIS branches
   (REVIEW band signal, weak signal, no match).
3. Assign priority: Class AB → HIGH (0), Class A → MEDIUM (1).
4. Convert to GeoJSON Features with `[lon, lat]` coordinates (the
   pipeline uses `[lat, lon]` internally, so this skill flips order).
5. Write `osm-audit-<zone>/maproulette/<zone>-class-a-unverified.geojsonl`.

The output is uploaded via the MapRoulette web UI or `mr-cli`.

## When to invoke

- "MapRoulette" / "crowdsource review" / "community review"
- "Create a challenge for `<zone>`"
- After a scan completes and Class A/AB findings need human triage
  beyond the auto-submit pool.

## What it produces

- A `.geojsonl` file (newline-delimited GeoJSON Features) at
  `osm-audit-<zone>/maproulette/<zone>-class-a-unverified.geojsonl`.
- One Feature per OSM way, with `task_name`, `task_instruction`
  (Markdown), `osm_link`, `priority`, and (when available)
  `cagis_match`.

## Related skills

- [`zone-audit`](zone-audit.md): produces the input
  `scan-results.json`.
- [`cagis-conflate`](cagis-conflate.md): supplies the
  `cagis_match.confidence` filter that this skill uses to skip
  auto-submittable ways.
- [`changeset-submit`](changeset-submit.md): handles the OTHER half
  (auto-submittable ways at confidence ≥ 0.85). MapRoulette is the
  community-review channel; changeset-submit is the mechanical-fix
  channel.

## See also

- [`SKILL.md`](../../.claude/skills/maproulette-challenge/SKILL.md)
- [`docs/explainers/maproulette-tasks.md`](../explainers/maproulette-tasks.md)
- [MapRoulette docs](https://learn.maproulette.org/)
