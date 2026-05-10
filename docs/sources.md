# External sources: what's used, what's not, and why

Reference for future-you (and fresh AI sessions) so each new
candidate-source URL doesn't get re-evaluated from scratch. When you
encounter a new feed, dataset, or third-party tool, add it here with
the rationale, even if the answer is "no."

## Active: currently in production

| Source | Module / file | What it provides | Citation form |
|---|---|---|---|
| **OSM Overpass API** | `osm.fetch` (`fetch.py:115`) | TIGER-import + driveable-network harvest per zone | `source=` tag (per fix kind) |
| **CAGIS Open Data Hub: Street Centerlines** (FeatureServer/26) | `osm.conflate` (`conflate.py:309`) | Authoritative Hamilton County street centerlines for fix verification | `cagis:attribution` tag, mandatory on every CAGIS-evidence changeset (`conflate.py:76-79`) |
| **CAGIS Open Data Hub: Metro Bus Routes** (FeatureServer/46, 202 features) | `osm.bus_routes` | Transit-corridor corroboration for `oneway_conflicts` detector | Implicit; informs the detector's confidence, not a tag |
| **TIGER/Line 2024 county roads** | `osm.tiger2024` | Fallback ground truth (less current, coarser-class than CAGIS) | `source=` tag with TIGER attribution; fix marked `requires_human_review=True` |
| **TIGER FIPS 39061 boundary** | `src/osm/zones/hamilton-county.geojson` | Polygon-clip fallback for bbox bleed past county line | Bundled in repo |
| **Mobility Database catalog (`mdb-366`)** | `osm.gtfs` | Resolves the SORTA GTFS feed URL | Used internally for stop cross-checks |
| **Transit App API** | `osm.transit` | Per-stop service quality / nearby-stop data; `fcntl.flock`-guarded usage counter; "Powered by Transit" attribution shipped in Atlas footer | "Powered by Transit" verbatim attribution |
| **OSM Notes API** | `osm.notes` | Open-note enrichment for `extra_findings` (`near_note` field) | None (read-only) |
| **Osmose** | `osm.osmose` | Quality-issue cross-reference | None (read-only) |
| **BRouter** (public service at brouter.de) | `osm.route_diff` | Default routing engine for rider-impact false-positive filtering | None (no submission cycle) |
| **MOTIS** (operator-pointed via `MOTIS_BASE`) | `osm.motis` | Opt-in multi-modal routing engine (OSM + GTFS in same graph) | None (degrades silently to BRouter) |
| **SORTA operational web map** (go-metro.com/riding-metro/metronow) | `src/osm/zones/<zone>.geojson` | Source of the four MetroNow zone polygons (one-time manual extract) | `docs/explainers/zone-data-flow.md` documents the extract path |

## Defensive backups: could swap in if a primary fails

| Source | What it would replace | Cost to wire up | When to consider |
|---|---|---|---|
| **Transitland** (`transit.land/feeds/f-dngy-southwestohioregionaltransitauthority`) | Mobility Database `mdb-366` for SORTA GTFS feed URL resolution | ~10 lines in `gtfs.py` (alternate resolver) | If Mobility Database drops `mdb-366` or rate-limits |
| **transitland-atlas** (`github.com/transitland/transitland-atlas`) repo | Same: registry-style feed lookup | Local clone or API call | Same |
| **Offline CAGIS snapshots** (the two `Open_Data_*.txt` ArcGIS dumps shared 2026-05-10: layer 45 = `Metro_Bus_Stops` 3,743 features; layer 46 = `Metro_Bus_Routes` 202 features) | Live CAGIS FeatureServer calls | Drop into `tests/fixtures/` or `data/cagis-snapshots/` and use as fixture loader | If CAGIS goes down or schema-changes during a scan; or for unit-test stability |

These are not wired up. They're documented so future-you knows they
exist if the primary breaks.

## Bookmark only: monitor but don't cite

These are useful for *operator awareness*, not as code citations or
changeset attributions.

| Source | Why monitor | What changes here means for the pipeline |
|---|---|---|
| `go-metro.com/plans-and-studies/` | SORTA service planning announcements | A MetroNow service-area expansion would require new zone polygons + `ZONES` dict entries |
| `go-metro.com/fall2026improvements/` | Forward-looking service changes (Fall 2026) | Same: possible zone refresh trigger |
| `go-metro.com/spring-2026-service-improvements/` | Already-announced spring 2026 changes | Confirm zone polygons match the post-spring-2026 footprint |
| OSMCha changeset feeds | Post-submission monitoring of `_cincyimport` account behavior | Already in scope via `osmcha-monitor` skill |
| ODOT TIMS Road Inventory | Aspirational additional ground-truth layer | Not yet wired; per `CLAUDE.md`, do **not** cite in `source=` tags until a working endpoint exists |

## Evaluated and out of scope

Sources that came up in conversation, were considered, and ruled out.
Documented here so the same evaluation doesn't run twice.

| Source | Why ruled out | Date evaluated |
|---|---|---|
| `metro-cincinnati.info` | Unaffiliated academic project from 2009-2012; documents a *hypothetical* Cincinnati rapid transit proposal, not real SORTA service. Author explicitly states no agency affiliation. The "© 2026" footer is automated copyright-year update, not content. | 2026-05-10 |
| `hansthompson/transit-tracker` (GitHub) | Third-party GTFS-Realtime tracker. MetroNow is static OSM corrections, not real-time transit. No relevance. | 2026-05-10 |
| `metrosystemmap.pdf` (SORTA fixed-route map) | MetroNow is microtransit (on-demand zones), not fixed-route. The fixed-route system is a different product. Useful as Cincinnati-transit context but not as a data source. | 2026-05-10 |
| `go-metro.com/riding-metro/fixed-route-schedules/` | Fixed-route schedules: same reason as above. | 2026-05-10 |
| **deep-wiki** plugin (`microsoft/skills/.github/plugins/deep-wiki`) | Generates VitePress-based docs from any repo. Adds toolchain surface that goes stale fast. The actual MetroNow docs problem was missing-middle gaps, not absent infrastructure. Solved instead by `metronow-explainer` skill + hand-curated `docs/explainers/`. | 2026-05-10 |

## How to add a new source

1. Decide which section: **Active** (already wired and used), **Defensive
   backup** (not wired but documented for fallback), **Bookmark** (monitor
   but don't cite), or **Out of scope** (evaluated and rejected).
2. Add a row to the appropriate table with: name + URL, what it
   provides / replaces / should be monitored for, citation form (if any),
   and date evaluated (Out-of-scope rows only).
3. If moving from Bookmark/Backup → Active, update the relevant module
   docstring (`gtfs.py`, `conflate.py`, etc.) so the source is also
   discoverable from the code side.
4. If a previously-active source is being deprecated, move it to Out of
   scope with a "deprecated YYYY-MM-DD" date and a one-line reason.

Keep this file flat and table-driven. It's a reference, not a narrative.
