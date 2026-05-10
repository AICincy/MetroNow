---
name: tiger-history-deep
description: Deep revision history analysis for specific OSM ways — fetches full version history from OSM API v0.6, identifies import bot vs human edits, classifies review status with confidence scores.
when_to_use: "User mentions a specific way ID, asks about edit history, checks if a way was reviewed, discusses INCONCLUSIVE status, or wants to investigate a specific street"
allowed-tools: Read Grep Glob Bash(python *) Bash(curl *)
argument-hint: "[way-id or street-name]"
arguments: [target]
---

# Deep Revision History Analysis

Investigate: **$target**

## Why this matters

The core innovation of this project (per Minh Nguyen's feedback) is that `tiger:reviewed=no` is unreliable. Most mappers don't remove the tag after correcting data. Deep history analysis is the only way to determine if a way has been meaningfully reviewed since the 2007 TIGER import.

## Analysis tiers (from history_filter.py)

### Tier 1: Fast check (from `out meta` data already in scan results)
- `version == 1` and `user == "DaveHansenTiger"` → definitely UNREVIEWED
- Last edited recently by a human mapper → likely REVIEWED
- Ambiguous → proceed to Tier 2

### Tier 2: Full history (OSM API call)
- `GET /api/0.6/way/{id}/history` — all versions of the way
- `GET /api/0.6/node/{id}/history` — for nodes along suspicious ways
- Analyze what changed between versions:
  - Was the change to **geometry** (node positions moved)?
  - Was the change to **tags** (highway, oneway, name corrected)?
  - Was it **incidental** (only `tiger:*` tags added/removed)?
  - Was `oneway` explicitly set by a human or inherited from import?

### Output per way
- `review_status`: UNREVIEWED | LIKELY_REVIEWED | INCONCLUSIVE
- `review_confidence`: 0.0 – 1.0
- Edit timeline: who changed what, when

## Known import bot accounts

These edits do NOT count as human review:
- `DaveHansenTiger` — original 2007-2008 TIGER import
- Abbreviation-expansion bot (December 2012) — automated name cleanup
- January 2010 node-tag cleanup — removed `source=tiger_import_dch_v0.6_*` tags from nodes

## Rate limiting

- OSM API allows ~1 request/sec for history endpoints
- Cache responses to `~/.config/osm/history_cache/` with 7-day TTL
- For bulk analysis, the scan pipeline's `--skip-history` flag exists for speed

## Current scan results

!`for d in osm-audit-*/; do f="$d/scan-results.json"; [ -f "$f" ] && echo "  ${d%/}: $(python -c "import json; print(json.load(open('$f'))['summary_stats']['total'])") ways"; done 2>/dev/null || echo "  (no scans yet)"`
