---
name: osmcha-monitor
description: Set up and query OSMCha monitoring for MetroNow zone changesets. Post-submission monitoring via REST API, pre-submission scoring via local osmcha Python package.
when_to_use: "User mentions OSMCha, monitoring edits, checking changesets, scoring proposed edits, or reviewing edit impact"
allowed-tools: Read Grep Glob Bash(python *) Bash(curl *)
argument-hint: "[changeset-id or zone]"
arguments: [target]
---

# OSMCha Monitoring

Monitor or score edits for: **$target**

## Two modes of operation

### Post-submission monitoring (REST API)
The OSMCha REST API at `osmcha.org/api/v1/changesets/{id}/` requires a changeset ID and only works after submission. Use this to:
- Review the pipeline's own changesets after they land
- Monitor concurrent edits by other mappers in the MetroNow zones
- Subscribe to RSS feeds for the four zone bboxes

### Pre-submission scoring (local Python)
The `osmcha` Python package (PyPI: `OSMCha/osmcha`) flags suspicious changesets locally using configurable thresholds:
- `create_threshold=200` — flag if creating more than 200 elements
- `modify_threshold=200` — flag if modifying more than 200 elements
- `top_threshold=1000` — flag if total changes exceed 1000

## Zone bounding boxes for saved filters

!`python -c "import sys; sys.path.insert(0, 'src'); from osm.zones import ZONES; [print(f'  {k}: bbox={v[\"bbox\"]}') for k,v in ZONES.items()]"`

## Setting up RSS monitoring

Create OSMCha saved filters for each zone:
```
https://osmcha.org/api/v1/changesets/?in_bbox={w},{s},{e},{n}
```

The web UI at http://localhost:3000 should subscribe to these feeds so reviewers see:
- Impact of the pipeline's own edits
- Any concurrent edits in the same zones that might conflict
- Edits by known TIGER cleanup accounts

## Post-submission review checklist

After submitting a changeset:
1. Wait 5-10 minutes for OSMCha to index it
2. Query `osmcha.org/api/v1/changesets/{changeset_id}/` for the analysis
3. Check for flags: large bbox, many modifications, tag changes
4. If flagged, review in OSMCha's web UI before continuing with more edits
5. Document the changeset URL in the project's review log
