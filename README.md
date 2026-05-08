# MetroNow

A read-and-write audit pipeline for the OpenStreetMap road network in the four
SORTA MetroNow microtransit zones of Hamilton County, Ohio. The system harvests
candidate defects from Overpass, classifies them against published TIGER-fixup
heuristics, ground-truths a subset against the Cincinnati Area GIS (CAGIS) Open
Data Hub, and submits verified corrections back to OSM via OAuth 2.0 changesets.

## Why this matters

Via Transportation operates [MetroNow](https://www.go-metro.com/metronow) for
SORTA. Via's product documentation states unambiguously that the routing graph
underlying ViaAlgo — their dispatch engine — is built from OpenStreetMap through
a custom layer called ViaMapping. Defects in OSM therefore propagate, after
Via's next ingest cycle, into the routing tiles consumed by every MetroNow
trip: refused turns, circuitous detours, "no service available" responses on
real public streets, ETAs derived from misclassified highway types.

The 2007–2008 TIGER/Line bulk import (`DaveHansenTiger`, MTFCC switch) seeded
many of these defects. Subsequent cleanup bots stripped the diagnostic
`tiger:reviewed=no` and even `tiger:cfcc` markers from a non-trivial fraction
of ways without correcting the underlying geometry — the false `oneway=yes`,
the `highway=residential` default that should have been `unclassified` or
`tertiary`, the over-connected nodes at grade separations. The pipeline is
designed to find those defects regardless of whether the TIGER provenance
markers survive.

## Pipeline phases

1. **Harvest** — `src/osm/fetch.py`. A union Overpass QL query fetches three
   element types within each zone bounding box: ways carrying `tiger:cfcc`
   (the canonical TIGER origin marker); ways with `highway` ∈ {residential,
   unclassified, tertiary, service} and `oneway=yes` (the defect signature
   itself, regardless of provenance); and the supporting auxiliary elements
   needed by the rider-impact detectors — `relation[type=restriction]`,
   `node[barrier]`, `node[highway=bus_stop]`, `node[entrance]`. Results are
   cached on disk under `osm-audit-{zone}/data/` with bbox-keyed pruning.
   Post-fetch, `src/osm/polygons.py` clips elements to each zone's
   authoritative MetroNow operational polygon (sourced from SORTA's
   published web map, see `src/osm/zones/<zone-key>.geojson`); ways /
   nodes whose centroid falls outside the polygon are dropped before
   classify and conflate run.

2. **Classify** — `src/osm/classify.py`. Original TIGER-fixup taxonomy:

   | Class | Predicate | Severity |
   |-------|-----------|----------|
   | **AB** | residential/unclassified/tertiary/service way is `oneway` (truthy: `yes`/`true`/`1`/`-1`) AND shares a normalized name with ≥1 other way in zone | CRITICAL |
   | **A**  | same as AB without the multi-segment co-occurrence | CRITICAL |
   | **B**  | normalized-name multi-segment grouping without false-oneway | HIGH |
   | **C**  | residual: in harvest, no class-A/B signal | LOW |

   Plus haversine-based node-disconnect detection between class-B segments
   (`src/osm/gaps.py`) with 30 m proximity threshold and 5 m junction
   clustering.

3. **Detect (rider-impact)** — `src/osm/detectors.py`. Eight non-TIGER
   detectors operate over the harvested ways, nodes, and relations. These
   surface defects that affect MetroNow rider experience independently of
   whether a way carries any `tiger:*` tag:

   | Detector | Predicate | Routing impact (1–5) |
   |----------|-----------|----------------------|
   | `oneway_minus_one` | `oneway=-1` on a class-A highway type | 4 |
   | `oneway_conflicts` | same-name parallel ways with same-direction `oneway`; legitimate divided carriageways excluded by lateral-vs-longitudinal-offset filter | 5 |
   | `access_blocked_residential` | `access` ∈ {`no`,`private`} on `highway=residential`, excluding `motor_vehicle=destination` (gated communities) | 5 |
   | `barriers_without_access` | `barrier` ∈ {`gate`,`bollard`,`lift_gate`,`swing_gate`,`cycle_barrier`} with no access qualifier | 4 |
   | `broken_turn_restrictions` | `relation[type=restriction]` missing `from`/`via`/`to` member, or empty `restriction` tag | 4 |
   | `arterial_named_residential` | `highway=residential` whose name terminates in Boulevard/Parkway/Expressway/Pike/Highway/Crossing/Memorial | 3 |
   | `missing_maxspeed_arterial` | `highway` ∈ {tertiary, unclassified} without `maxspeed` | 3 |
   | `misplaced_bus_stops` | `highway=bus_stop` whose nearest drivable-way vertex exceeds 20 m | 2 |

   Each finding carries an explicit `routing_impact` score; the UI surfaces
   them in an inventory panel sorted by impact descending.

4. **Conflate (ground truth)** — `src/osm/conflate.py`. Optional but
   load-bearing for mechanical edits. Pulls Cincinnati Area GIS Street
   Centerlines from FeatureServer/26 (a paginated REST query at
   2,000 records/page, cached 90 days), constructs a Shapely 2.x STRtree
   spatial index, and scores every harvested OSM way against the nearest
   CAGIS centerline:

   ```
   confidence = 0.5 · name_similarity         (Ratcliff-Obershelp on normalized names)
              + 0.3 · geometry_overlap        (1 − directed-Hausdorff/30 m, OSM→CAGIS only)
              + 0.2 · direction_alignment     (|cos θ| between line direction vectors)
   ```

   The geometry term uses **directed** Hausdorff (max-over-OSM-points of
   min-distance-to-CAGIS-line). The symmetric form blew up on the common
   topology where OSM has a long named street broken into shorter ways at
   intersections — the reverse direction penalised CAGIS endpoints lying
   outside the OSM segment even when OSM perfectly traced its part. Real
   data: switching to directed Hausdorff lifted Blue Ash's auto-submit
   rate from 6.3% to 17.7% (and 5.0% → 12.1% across all four zones).

   At confidence ≥ 0.85 the conflated way is treated as ground-truth: CAGIS
   `TRVL_DIR` overrides the OSM `oneway` heuristic, CAGIS `SPEEDLIMIT`
   supplies a missing `maxspeed`, CAGIS `STRLABEL` flags a name mismatch
   (always queued for human review — CAGIS uses postal abbreviations, OSM
   convention is spelled-out names). Confidence in [0.6, 0.85] surfaces the
   way as a candidate but blocks auto-submission.

   When the STRtree query returns no candidates within 30 m, a
   nearest-neighbor fallback queries the absolutely closest CAGIS feature
   and, if within 100 m, scores it normally but **caps confidence at
   `REVIEW_CONFIDENCE` (0.6)** — fallback hits surface in the human-review
   queue but never auto-submit. The `osm conflate --baseline-manifest`
   flag emits a per-zone diagnostic JSON attributing every way to one of
   `MATCHED_HIGH` / `MATCHED_REVIEW` / `MATCHED_FALLBACK_REVIEW` /
   `F1_NO_CANDIDATE` / `F2_NAME_FAIL` / `F3_GEOMETRY_FAIL` /
   `F4_DIRECTION_DRAG` / `MIXED_LOW`, used for matcher tuning.

5. **Review** — `src/osm/review.py`. `proposed_fixes_for_way` emits zero or
   more fix descriptors per way, each tagged with its evidence: pure
   classifier (`remove_false_oneway`) or CAGIS-verified (`remove_oneway_cagis`,
   `set_oneway_cagis`, `set_maxspeed_cagis`, `set_name_cagis`). The UI
   distinguishes the two visually and excludes the eight rider-impact
   detector outputs from the mechanical-edit Fix panel — those require human
   review.

6. **Submit** — `src/osm/changeset.py`. Creates batched OSM API v0.6
   changesets (≤ 500 elements per the community norm; CGImap hard limit is
   10,000). Required tags: `comment`, `source=survey;CAGIS Open Data Hub`,
   `created_by=MetroNow TIGER Audit Pipeline/0.1`, `mechanical=yes`,
   `bot=yes`, `description=<wiki URL>`. CAGIS-verified fixes additionally
   carry `cagis:attribution` to satisfy the Open Data Hub license.

7. **Report** — `src/osm/{xlsx,dashboard,csv_export}.py`. Eight-sheet XLSX
   workbook, self-contained Leaflet HTML dashboard, four sorted CSV slices.

## Service zones

| Zone key | Communities served | Index-case street |
|----------|--------------------|--------------------|
| `blue-ash-montgomery`     | Blue Ash, Montgomery, Deer Park, Silverton, Kenwood, Madeira | Main Avenue |
| `springdale-sharonville`  | Springdale, Sharonville, Glendale, Evendale, Lincoln Heights | — |
| `northgate-mt-healthy`    | Mt. Healthy, North College Hill, Finneytown, Northgate | — |
| `forest-park-pleasant-run`| Forest Park, Pleasant Run, Greenhills | — |

Bounding boxes are defined in [`src/osm/zones.py`](src/osm/zones.py); the
pipeline does not assume a one-to-one match between bbox and Via's published
service polygon. A trip whose origin or destination falls outside a zone's
bbox but inside Via's actual service area is, today, unaccounted for; closing
this gap requires the operator polygon GeoJSON, which is not publicly
distributed.

## Quickstart

Requires Python 3.12+ and Node.js 20+. Shapely 2.0+ is required for
conflation; if absent, the rest of the pipeline still runs and conflation
degrades to a no-op with a warning.

```bash
pip install -e ".[dev]"
cd web && npm install && npm start
```

Open `http://localhost:3000`.

CLI usage:

```bash
osm scan --zone blue-ash-montgomery                    # standard scan
osm scan --zone blue-ash-montgomery --with-conflation  # add CAGIS ground truth
osm scan --zone all                                    # all four zones
osm conflate --zone blue-ash-montgomery                # conflate against existing scan
osm fix --zone blue-ash-montgomery --dry-run           # preview corrections
osm fix --zone blue-ash-montgomery                     # submit changesets
osm auth login                                         # OSM OAuth 2.0 (PKCE)
```

## Verification (state of main as of last commit)

- **273 passing tests** across `tests/test_{classify,gaps,geo,history_filter,review,detectors,conflate,notes,osmose,route_diff,tiger2024,polygons,gtfs,maproulette,bus_routes}.py`.
- `ruff check src/` clean. `mypy src/osm/ --ignore-missing-imports` clean.
- Four-zone CAGIS conflation snapshot, post-Phase-4a stage 3 (real
  MetroNow operational polygons sourced from SORTA's published web
  map). Total ways count post-polygon-clip elements; auto-submit
  counts ways at confidence ≥ 0.85; review counts in-buffer 0.6–0.85
  plus fallback hits capped at 0.6:

  | Zone                        | Total ways | Auto-submit (HIGH) | Review queue | Match rate |
  |-----------------------------|-----------:|-------------------:|-------------:|-----------:|
  | Blue Ash / Montgomery       | 3,642      | 19.99% (728)       | 5.35% (195)  | **25.34%** |
  | Springdale / Sharonville    | 4,235      | 15.04% (637)       | 7.72% (327)  | **22.76%** |
  | Northgate / Mt. Healthy     | 1,409      | 21.22% (299)       | 5.18% (73)   | **26.40%** |
  | Forest Park / Pleasant Run  | 1,898      | 19.97% (379)       | 3.37% (64)   | **23.34%** |

  Match rate ≥ 22.76% in every zone; auto-submit rate ≥ 15% in every
  zone. Stage 3 tightens audit scope to the actual operational service
  polygons, so corrections target ways that affect MetroNow rider
  experience instead of the broader bbox. Per-way diagnostic manifests
  with bucket attribution (`MATCHED_HIGH` / `MATCHED_REVIEW` /
  `MATCHED_FALLBACK_REVIEW` / `F1_NO_CANDIDATE` / `F2_NAME_FAIL` /
  `F3_GEOMETRY_FAIL` / `F4_DIRECTION_DRAG` / `MIXED_LOW`) are written by
  `osm conflate --baseline-manifest`.

## Compliance and provenance

This project performs mechanical edits to a public, community-governed
geographic database. Every changeset must comply with the OSM
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct):

- Edits must be documented in advance on a wiki page; see the project
  changeset's `description` tag for the link.
- Discussion on `talk-us@` and `community.openstreetmap.org` is required
  before bulk runs in a new area.
- Changesets are tagged `mechanical=yes`, `bot=yes`, and carry the project
  source attribution.
- Opt-out requests must be honored immediately.
- Changesets stay well below the 10,000-element CGImap limit; the project
  default is 500 elements/batch to keep diff review tractable in OSMCha.

CAGIS data is used "as is" per the Open Data Hub license; attribution is
written into every CAGIS-sourced changeset via the `cagis:attribution` tag.

## Background

Successor to [AICincy/Tiger](https://github.com/AICincy/Tiger), which
detected defects via the now-deprecated `tiger:reviewed=no` filter. Per
community feedback from [Minh Nguyen](https://wiki.openstreetmap.org/wiki/User:Mxn),
that tag is unreliable in both directions: cleanup bots strip it without
fixing the geometry, and human mappers leave it in place after correcting
the data. This pipeline replaces the single-tag heuristic with a union query
(TIGER origin marker ∪ defect signature), layered with eight rider-impact
detectors that operate independently of TIGER provenance, and grounded
against CAGIS Street Centerlines for verifiable mechanical fixes.

[`RESEARCH-FINDINGS.md`](RESEARCH-FINDINGS.md) holds the full investigation
into Via's data architecture, the TIGER defect taxonomy, the OSM API v0.6
constraints, and the OSM community process requirements. Read it before
opening a PR that changes the defect detectors or the changeset submission
path.

## License

[MIT](LICENSE).
