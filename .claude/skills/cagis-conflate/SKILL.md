---
name: cagis-conflate
description: Cross-reference OSM data against CAGIS quarterly road centerlines and ODOT TIMS Road Inventory for ground-truth validation of defect classifications.
when_to_use: "User mentions CAGIS, ODOT, ground truth, cross-reference, validate classification, compare centerlines, or check highway type"
allowed-tools: Read Grep Glob Bash(python *) Bash(curl *)
argument-hint: "[zone or way-id]"
arguments: [target]
---

# CAGIS Ground-Truth Conflation

Cross-reference OSM against authoritative sources for: **$target**

## Authoritative datasets (from RESEARCH-FINDINGS.md)

### CAGIS Open Data Hub
- URL: `data-cagisportal.opendata.arcgis.com`
- Content: Quarterly-updated road centerlines + addresses for Hamilton County
- License: Public-domain-equivalent (City of Cincinnati). Requires disclaimer + credit in `source=` changeset tag
- Accuracy: National Map Accuracy Standards for 1"=100' base map, NAD83
- Use for: Road geometry validation, address verification, new road detection

### ODOT TIMS Road Inventory
- URL: `tims.dot.state.oh.us`
- Content: State-certified mileage for HPMS reporting; annual update
- License: No copyright per ODOT GISP Ian Kidner
- Attributes: Lane miles, federal-aid eligibility, speed zones, NHS designation
- Use for: Highway classification ground truth (is this road state highway? federal-aid? what speed zone?)
- TMS tiles: `https://tiles.mblaine.com/ohio/{z}/{x}/{y}.png` (mblaine's Mapnik render of ODOT data)

### TIGER/Line 2024
- File: `tl_2024_39061_roads.zip` (Census Bureau, FIPS 39061 = Hamilton County)
- Released: September 26, 2024; data through May 2024
- Use for: "What would TIGER look like today" reference — differences vs 2005-imported OSM are cleanup candidates

## Conflation workflow

1. **Ingest** — Download CAGIS road centerlines into PostGIS (or local GeoJSON)
2. **Buffer match** — For each OSM way, find CAGIS centerlines within a buffer distance
3. **Hausdorff distance** — Score geometric similarity between matched pairs
4. **Attribute compare** — Check highway classification, name, oneway against CAGIS
5. **Flag mismatches** — Ways where OSM says `highway=residential` but CAGIS says connector/arterial

## Key misclassification pattern

The 2007 TIGER import mapped CFCC A4x codes to `highway=residential` by default (RESEARCH-FINDINGS Item 3). Many should be:
- `highway=unclassified` (rural connectors)
- `highway=tertiary` (suburban arterials)
- `highway=service` (driveways/alleys)

CAGIS and ODOT TIMS are the authoritative sources to determine the correct classification.

## Source attribution

Every changeset that uses CAGIS data must include:
```
source=CAGIS Open Data Hub (data-cagisportal.opendata.arcgis.com)
```
with the required disclaimer and data creator credit per CAGIS terms.
