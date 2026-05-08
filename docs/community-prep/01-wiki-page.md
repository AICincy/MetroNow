<!--
This is a draft of the OSM wiki page that documents the MetroNow audit
pipeline, per the Automated Edits code of conduct. Paste the content
below (everything between the ===== markers, with the ====='s removed)
into a NEW page at:

  https://wiki.openstreetmap.org/wiki/Automated_edits/<your_account_name>

Replace <YOUR_ACCOUNT_NAME>, <CONTACT_EMAIL>, and <START_DATE> in the
content before saving.
-->

# Wiki page draft — `Automated_edits/<YOUR_ACCOUNT_NAME>`

=====

# MetroNow OSM TIGER Audit

This page documents the mechanical edits made by the
[`<YOUR_ACCOUNT_NAME>`](https://www.openstreetmap.org/user/<YOUR_ACCOUNT_NAME>)
account against OpenStreetMap data in Hamilton County, Ohio. The edits
correct defects inherited from the 2007–2008 TIGER/Line bulk import that
affect the routing graph used by SORTA's MetroNow on-demand
microtransit service. Source code, audit reports, and per-edit evidence
are in [github.com/AICincy/MetroNow](https://github.com/AICincy/MetroNow).

## Why

[MetroNow](https://www.go-metro.com/riding-metro/metronow/) is operated
for SORTA by Via Transportation. Via's product documentation states
unambiguously that ViaAlgo (the dispatch engine) consumes OpenStreetMap
through a custom layer called ViaMapping, with operator-specific
augmentations on top. Defects in OSM in the four MetroNow service
zones therefore propagate, after Via's next ingest cycle, into the
routing tiles every MetroNow trip relies on: refused turns, circuitous
detours, "no service available" responses on real public streets, and
ETAs derived from misclassified highway types.

The 2007–2008 TIGER/Line import (DaveHansenTiger, MTFCC switch) seeded
many of these defects in northern Hamilton County's suburban arterials
— exactly where MetroNow operates today. Subsequent cleanup bots
stripped the diagnostic `tiger:reviewed=no` and even `tiger:cfcc`
markers from a non-trivial fraction of ways without correcting the
underlying geometry. The audit pipeline finds these defects regardless
of whether the TIGER provenance markers survive.

## Scope

* **Geographic.** Four MetroNow operational service polygons, traced
  from SORTA's published web map (ArcGIS Online item
  [`ba2063d68a3e41bd86d486d372991d65`](https://www.arcgis.com/home/item.html?id=ba2063d68a3e41bd86d486d372991d65),
  `metro_mlinder`, public). Polygons buffered 200 m and clipped to the
  Hamilton County boundary. No edits outside Hamilton County.
* **Element types.** OSM `way` elements only; no node, relation, or
  changeset comment edits. Way modifications are tag-only — no
  geometry edits.
* **Tags edited.** Only `oneway`, `maxspeed`, and (deferred for now)
  `name`. Specifically:
  * `set_maxspeed_cagis` — adds `maxspeed=<N> mph` when CAGIS publishes
    a speed limit and OSM has no `maxspeed` tag.
  * `set_oneway_cagis` — adds `oneway=yes` or `oneway=-1` when CAGIS
    `TRVL_DIR` indicates directionality and OSM disagrees.
  * `remove_oneway_cagis` — removes a false `oneway=yes` when CAGIS
    `TRVL_DIR=0` (bidirectional) and OSM has it tagged as one-way.

## How fixes are decided

A fix is auto-submitted only when **all** of these are true:

1. The OSM way's centroid is inside the published MetroNow service
   polygon for one of the four zones.
2. CAGIS published its own centerline within 30 m of the OSM way
   (directed Hausdorff, OSM→CAGIS).
3. The conflation confidence is ≥ 0.85, computed as
   `0.5 × name_similarity + 0.3 × geometry_overlap + 0.2 × direction_alignment`.
4. The fix is one of the three kinds listed above.
5. (For oneway fixes) BRouter's route-impact decision is `real`
   (>15% route-cost delta) — verified by the
   [`osm fix-impact`](https://github.com/AICincy/MetroNow/blob/main/src/osm/route_diff.py)
   subcommand against the live BRouter endpoint at brouter.de.

Anything in the 0.6 ≤ confidence < 0.85 band goes to a human-review
queue surfaced in the project's web UI ("Investigations" panel) and
the per-zone MapRoulette challenge — never auto-submitted.

## Changeset metadata

Every changeset created by `<YOUR_ACCOUNT_NAME>` carries:

| Tag | Value |
|-----|-------|
| `comment` | Per-batch description, names the zone and the fix kind |
| `created_by` | `MetroNow TIGER Audit Pipeline/0.1` |
| `source` | `survey;CAGIS Open Data Hub` |
| `mechanical` | `yes` |
| `bot` | `yes` |
| `description` | URL of this wiki page |
| `cagis:attribution` | `Source: CAGIS Open Data Hub, Hamilton County, Ohio (https://cagisonline.hamilton-co.org/) — used as-is per license.` |

## Frequency, volume, and rate

* **Polite-rate-limit:** ≤ 500 elements per changeset (community norm).
  CGImap's hard limit is 10,000.
* **Frequency:** at most one batch per zone per day during the initial
  ramp; no more than 1,000 elements per hour total (the new-account
  default cap).
* **First batch:** 10 elements only. After 72 hours of OSMCha-clean
  behaviour, scale to ~50, then ~200, then ~500.
* **Total expected size:** the auto-submit pool across all four zones
  is currently ~2,043 fixes (1,300+ are `set_maxspeed_cagis`).

## Opt-out

Any local mapper or community member may request that
`<YOUR_ACCOUNT_NAME>` cease editing a particular street, zone, or any
specific way. Opt-outs are honoured immediately; reach the maintainer
via:

* Email: <CONTACT_EMAIL>
* OSM messages: <https://www.openstreetmap.org/user/<YOUR_ACCOUNT_NAME>>
* GitHub issue: <https://github.com/AICincy/MetroNow/issues>

A revert without notice is acceptable if you believe the edit damaged
data. Please file an issue afterward so the pipeline can be tightened.

## Source ground truth

* **CAGIS Street Centerlines** — Cincinnati Area GIS Open Data Hub,
  FeatureServer/26, quarterly updates.
* **TIGER/Line 2024** — U.S. Census Bureau, FIPS 39061 county roads,
  used as a fallback layer where CAGIS coverage is incomplete.
* **MetroNow zone polygons** — SORTA's published web map (linked
  above), 200 m buffered, intersected with Hamilton County polygon
  (Census TIGERweb FIPS 39061).

## Discussion history

This page was published on <START_DATE>. Discussion thread:

* `talk-us@openstreetmap.org`: <LINK_TO_THREAD_OR_ARCHIVE>
* `community.openstreetmap.org`: <LINK_TO_THREAD>
* Local OSM-US Cincinnati Slack: <CHANNEL_REFERENCE>

A two-week comment window opened on <START_DATE>. The first
mechanical-edit batch shipped no earlier than <START_DATE + 14 days>.

## Process compliance

This audit follows the
[OSM Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct):

* Documented in advance on this page (created <START_DATE>).
* Discussed publicly on `talk-us@` and `community.openstreetmap.org`
  before any production edit.
* Tagged `mechanical=yes` and `bot=yes` per the convention.
* Honours opt-outs immediately.
* Local convention (`_cincyimport` account suffix) followed, per the
  precedent set by the Hamilton County Building Import.

=====

<!--
End of paste content. Below this line are notes for the maintainer
that should NOT be pasted into the wiki.

Notes:
- Replace <YOUR_ACCOUNT_NAME> in 4 places, <CONTACT_EMAIL> in 1 place,
  <START_DATE> in 3 places, and <LINK_TO_THREAD*> in 3 places before
  saving the wiki page.
- The wiki page URL becomes the value of every changeset's
  `description` tag — set it in src/osm/config.py:WIKI_URL after
  publishing.
- The MapRoulette challenges from `osm maproulette --zone <key>`
  reference the same wiki URL in their per-task instructions.
- Bookmark this page; you'll link it from the talk-us@ post in
  `02-talk-us-post.md`.
-->
