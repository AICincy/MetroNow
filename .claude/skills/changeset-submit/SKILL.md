---
name: changeset-submit
description: Submit corrections to OSM API v0.6 with full community compliance — proper changeset tags, size limits, rate-limit awareness, and dry-run support.
when_to_use: "User says submit, push corrections, fix, create changeset, dry run, or wants to apply corrections to OpenStreetMap"
allowed-tools: Read Grep Glob Bash(python *)
argument-hint: "[zone] [--dry-run]"
arguments: [zone, flags]
---

# Changeset Submission

Submit corrections for zone **$zone** with flags: **$flags**

## Pre-submission checklist

Before ANY changeset submission, verify:

- [ ] OAuth token is valid: check http://localhost:3000 Authenticate tab
- [ ] Community prep is complete: run `/community-prep` first
- [ ] Wiki documentation page exists at `wiki.openstreetmap.org/wiki/Automated_edits/<username>`
- [ ] `talk-us@` discussion has been posted
- [ ] Dedicated `_cincyimport`-convention account is configured
- [ ] Scan results exist for the target zone

## Current auth state

!`test -f "$HOME/.config/osm/token.json" && echo "Token file exists" || echo "NO TOKEN - authenticate first at http://localhost:3000"`

## Hard limits (RESEARCH-FINDINGS Section 3, Item 1)

| Limit | Value | Source |
|-------|-------|--------|
| Elements per changeset | 10,000 (CGImap hard limit) | OSM API v0.6 docs |
| Community norm | ~500 elements | Mechanical edit convention |
| New account first day | 1,000 changes/hour | PR #4319 ramp curve |
| Established account | 100,000 changes/hour | After ~1 week |
| Tag value length | 255 Unicode codepoints | API spec |

## Required changeset tags

Every changeset MUST include:
```xml
<tag k="comment" v="TIGER defect correction in MetroNow {zone_name} zone: {description}"/>
<tag k="source" v="survey;CAGIS Open Data Hub"/>
<tag k="mechanical" v="yes"/>
<tag k="created_by" v="MetroNow TIGER Audit Pipeline"/>
<tag k="description" v="https://wiki.openstreetmap.org/wiki/Automated_edits/{username}"/>
```

## Submission workflow

1. **Load accepted fixes** from `review.py` output or scan results
2. **Split into batches** of ~500 elements (well under 10K hard limit)
3. **Poll rate limits** at `/api/0.6/capabilities` before each batch
4. **Open changeset** with required tags
5. **Apply modifications** (tag changes, not geometry changes for automated edits)
6. **Close changeset** and record the changeset ID
7. **Post-submission**: Run `/osmcha-monitor {changeset_id}` to verify

## Dry-run mode

With `--dry-run`, the pipeline generates the OsmChange XML and displays the diff without opening a changeset. Always do a dry run first.
