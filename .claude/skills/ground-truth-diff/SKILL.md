---
name: ground-truth-diff
description: Diff OSM geometry and attributes against TIGER/Line 2024 to identify import drift, new roads, and name-field artifacts in MetroNow zones.
when_to_use: "User mentions TIGER 2024, geometry drift, name artifacts, new roads, comparing OSM to Census data, or Mac Donald / O Toole style name errors"
allowed-tools: Read Grep Glob Bash(python *) Bash(curl *)
argument-hint: "[zone]"
arguments: [zone]
---

# Ground-Truth Diff Against TIGER 2024

Compare OSM against TIGER/Line 2024 for zone: **$zone**

## TIGER/Line 2024 source

- File: `tl_2024_39061_roads.zip` (Hamilton County, FIPS 39061)
- Download: Census Bureau TIGER/Line Shapefiles (released September 26, 2024)
- Data currency: Through May 2024
- 2025 vintage adds augmented fullname fields and address ranges

## What the diff reveals

### Geometry drift
Ways that were imported in 2007 from TIGER 2005 but have since been updated in the Census Bureau's data. Differences indicate either:
- OSM was corrected (good — confirms human review happened)
- OSM was NOT corrected and the road has actually moved/changed (cleanup candidate)

### New roads
Roads in TIGER 2024 that have no OSM equivalent — genuinely new construction since 2005. Particularly relevant for the MetroNow zones where suburban development is active.

### Name-field artifacts (RESEARCH-FINDINGS Section 2 Item 3)

The 2007 import introduced systematic name errors:
- **USPS abbreviation spacing**: "Mac Donald St" → should be "MacDonald Street"
- **Stripped apostrophes**: "O Toole Avenue" → should be "O'Toole Avenue"
- **Stripped diacritics**: "Canada Road" for "Cananda Road"
- **ALL CAPS remnants**: Some ways still have uppercase names from TIGER

TIGER 2024 has corrected many of these. Diffing reveals which OSM ways still carry the 2005-era name.

## Highway classification drift

The original import mapped CFCC A4x → `highway=residential` by default. TIGER 2024 uses updated MAF/TIGER Feature Class Codes (MTFCC) that better distinguish:
- S1400: Secondary road → `highway=tertiary` or `unclassified`
- S1740: Private road → `highway=service` + `access=private`
- S1200: Secondary road (named) → `highway=secondary`

Cross-referencing TIGER 2024 MTFCC against OSM `highway=*` reveals misclassifications.

## Diff workflow

1. Download `tl_2024_39061_roads.zip` from Census Bureau
2. Extract and load into a spatial format (GeoJSON, PostGIS, or Shapefile)
3. Clip to zone bbox from `src/osm/zones.py`
4. For each TIGER 2024 road segment:
   - Find matching OSM way(s) by proximity + name similarity
   - Compare: geometry (Hausdorff distance), name, MTFCC vs highway tag
   - Flag mismatches as correction candidates
5. Output: CSV of candidates with OSM way ID, TIGER LINEARID, and specific mismatches
