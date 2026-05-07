---
name: zone-audit
description: Run the full TIGER defect audit pipeline for a MetroNow service zone — fetch from Overpass, classify defects, analyze history, generate reports.
when_to_use: "User says scan, audit, check a zone, run an audit, or mentions a specific zone name like blue_ash_montgomery"
allowed-tools: Read Grep Glob Bash(node *) Bash(python *)
argument-hint: "[zone-name]"
arguments: [zone]
---

# Zone Audit Pipeline

Run the full audit pipeline for MetroNow zone: **$zone**

## Available zones

!`python -c "import sys; sys.path.insert(0, 'src'); from osm.zones import ZONES; [print(f'  {k}: {v[\"name\"]} — {v[\"description\"]}') for k,v in ZONES.items()]"`

## Current scan state

!`powershell -Command "Get-ChildItem -Path 'osm_audit_*' -Directory -ErrorAction SilentlyContinue | ForEach-Object { $r = Join-Path $_.FullName 'scan_results.json'; if (Test-Path $r) { Write-Output ('  ' + $_.Name + ' — last scan: ' + (Get-Item $r).LastWriteTime) } }"`

## Pipeline steps

1. **Fetch** — Query Overpass API using the DaveHansenTiger user+timestamp filter with `["highway"]` tag and `out meta geom` for full metadata. The query targets ways imported by `DaveHansenTiger` between 2007-08-03 and 2008-05-04 within the zone bbox. Retry logic: primary endpoint, 30s wait, primary again, then kumi mirror.

2. **Classify** — Assign defect classes:
   - **Class AB** (Critical): `highway=residential` + `oneway=yes` + multi-segment name — compound defect, highest routing impact
   - **Class A** (Critical): False `oneway=yes` on residential streets
   - **Class B** (High): 2+ ways sharing a normalized name with disconnect risk
   - **Class C** (Low): Unreviewed, no immediate defect signal

3. **Gap detection** — Haversine endpoint analysis with 30m threshold + 5m junction clustering to find disconnected road segments

4. **History filter** (optional) — Analyze OSM revision history to determine if ways have been meaningfully reviewed since import. Skip with `--skip-history` for faster scans.

5. **Reports** — Generate XLSX workbook (8 sheets), interactive Leaflet dashboard, and 4 CSV slices

## How to run

Start the web server if not running, then use the Scan tab at http://localhost:3000. Or run via Python:

```python
from pathlib import Path
from osm.fetch import fetch_overpass
from osm.classify import classify

out_dir = Path(f"osm_audit_{zone_key}")
raw = fetch_overpass(zone_key, out_dir)
classified = classify(raw)
```

## After scanning

- Check the stats grid for defect counts
- Review Class AB defects first (highest routing impact for MetroNow riders)
- Generate reports for the zone before proceeding to corrections
- If gap count is high, investigate node disconnects in JOSM or iD editor
