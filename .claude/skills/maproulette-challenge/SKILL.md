---
name: maproulette-challenge
description: Generate a MapRoulette challenge from scan results for defect classes with high false-positive rates. Creates GeoJSON tasks constrained to MetroNow zone polygons.
when_to_use: "User mentions MapRoulette, crowdsource review, needs human review for defects, or discusses Class B defects that need manual verification"
allowed-tools: Read Grep Glob Bash(python *) Bash(node *) Bash(curl *)
argument-hint: "[zone] [defect-class]"
arguments: [zone, defect_class]
---

# MapRoulette Challenge Creation

Generate a MapRoulette challenge for **$defect_class** defects in **$zone**.

## Why MapRoulette

Per RESEARCH-FINDINGS.md Item 17 and the OSM Automated Edits code of conduct: corrections with >5% expected false-positive rate must go through MapRoulette rather than direct API edits. This includes:
- Highway reclassification (A4x residential that should be unclassified/tertiary/service)
- Oneway flips in ambiguous cases (braided dual carriageways)
- Name-field corrections requiring local knowledge

## Current scan results

!`powershell -Command "$p = 'osm_audit_$zone\scan_results.json'; if (Test-Path $p) { python -c \"import json; d=json.load(open('$p')); s=d['summary_stats']; print(f'Total: {s[\"total\"]}, AB: {s[\"class_ab_count\"]}, A: {s[\"class_a_count\"]}, B ways: {s[\"class_b_way_count\"]}, Gaps: {s[\"gaps_found\"]}')\" } else { Write-Output 'No scan results found. Run /zone-audit first.' }"`

## MapRoulette API workflow

1. **Create Project** — POST to `https://maproulette.org/api/v2/project`
   - Name: `MetroNow TIGER Audit — {zone_name}`
   - Description: Link to wiki documentation page

2. **Create Challenge** — POST to `https://maproulette.org/api/v2/challenge`
   - Source: GeoJSON feed from scan results
   - AOI: Zone polygon from `src/osm/zones/__init__.py` (the `ZONES` dict)
   - Instructions: Per-defect-class fix guidance
   - Tags: `tiger`, `metronow`, `hamilton-county`

3. **Batch Tasks** — POST GeoJSON features as tasks
   - Each task = one OSM way with defect metadata
   - Include: way ID, street name, defect class, severity, OSM link, JOSM remote URL
   - Attach CAGIS imagery comparison if available

## Important constraints

- MapRoulette's Overpass query field is **read-only after task generation** — clone the challenge if the detection algorithm changes
- Use `mr-cli` for cooperative challenges with task attachments
- Constrain to MetroNow zone polygon AOI
- Link challenge to the wiki documentation page for the mechanical edit
