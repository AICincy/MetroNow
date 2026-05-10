# MetroNow

**Summary.** OSM road-defect detection and correction pipeline for the
four Hamilton County zones served by SORTA's [MetroNow](https://www.go-metro.com/metronow)
on-demand microtransit service. Via Transportation's ViaMapping
routing layer is built on OpenStreetMap — defects in OSM propagate,
on Via's next ingest, into the routing tiles every MetroNow trip
relies on. The pipeline harvests candidate defects from Overpass,
classifies them with a TIGER-fixup taxonomy, ground-truths a subset
against the Cincinnati Area GIS (CAGIS) Open Data Hub, and submits
verifiable corrections back to OSM via OAuth 2.0 changesets with
full community compliance.

---

## What this is

The 2007–2008 TIGER/Line bulk import (`DaveHansenTiger`) seeded a
generation of defects in OSM's Hamilton County coverage: false
`oneway=yes` on residential streets, over-connected intersections at
grade separations, `highway=residential` defaults that should have
been `unclassified` or `tertiary`. Subsequent cleanup bots stripped
the diagnostic `tiger:reviewed=no` and `tiger:cfcc` markers from a
non-trivial fraction of ways without correcting the underlying
geometry.

Defects in OSM propagate, after Via's next ingest cycle, into the
routing tiles consumed by every MetroNow trip: refused turns,
circuitous detours, "no service available" responses on real public
streets, ETAs derived from misclassified highway types. The pipeline
finds those defects regardless of whether the TIGER provenance markers
survive, ground-truths a subset against authoritative CAGIS centerlines,
and submits verifiable corrections under the OSM
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct).

## How it works

Seven pipeline stages, each implemented as a module under `src/osm/`:

```mermaid
---
title: "MetroNow audit pipeline"
---
flowchart LR
    Overpass["Overpass API<br/>(harvest by zone bbox)"]
    Polygons["polygons.py<br/>(centroid clip to zone polygon)"]
    Classify["classify.py<br/>(Class A / AB / B / C + gaps)"]
    Detectors["detectors.py<br/>(8 rider-impact detectors)"]
    History["history_filter.py<br/>(UNREVIEWED / LIKELY_REVIEWED /<br/>INCONCLUSIVE)"]
    Conflate["conflate.py<br/>(CAGIS centerlines, directed-Hausdorff)"]
    Review["review.py<br/>(3-layer fix-proposal stack)"]
    Changeset["changeset.py<br/>(OSM API v0.6 + CoC tags)"]
    MapRoulette["maproulette.py<br/>(community-review tasks)"]
    Reports["xlsx + dashboard + CSV"]

    Overpass --> Polygons --> Classify
    Classify -- "classifier track" --> History
    History --> Conflate
    Conflate -- "confidence ≥ 0.85" --> Review
    Conflate -- "0.6 ≤ confidence < 0.85" --> Review
    Review -- "auto-submit (verified)" --> Changeset
    Review -- "Class A/AB without HIGH" --> MapRoulette
    Classify -- "rider-impact track" --> Detectors
    Detectors --> MapRoulette
    Polygons & Classify & Detectors & Conflate & Review --> Reports

    classDef harvest fill:#3a3a3a,stroke:#888,color:#eee
    classDef analyse fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    classDef verify fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    classDef submit fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec,font-weight:bold
    class Overpass,Polygons harvest
    class Classify,Detectors,History,Reports analyse
    class Conflate,Review,MapRoulette verify
    class Changeset submit
```

The pipeline emits two parallel tracks. The **classifier track**
(Class A / AB / B / C plus gaps) is the only path to mechanical
auto-submission. The **detector track** (eight rider-impact checks)
ships findings to the UI for human triage; it never reaches
`changeset.py`. This split is the project's mechanical-edit safety
perimeter — see [`docs/explainers/detector-taxonomy.md`](docs/explainers/detector-taxonomy.md).

## Defect taxonomy (classifier track)

| Class | Predicate | Severity |
|---|---|---|
| **AB** | residential / unclassified / tertiary / service way is `oneway` (truthy: `yes`/`true`/`1`/`-1`) AND shares a normalized name with ≥1 other way in the zone | CRITICAL |
| **A** | same as AB without the multi-segment co-occurrence | CRITICAL |
| **B** | normalized-name multi-segment grouping without false-oneway | HIGH |
| **C** | residual: in harvest, no Class A/B signal | LOW |

Plus haversine-based node-disconnect detection between Class B
segments (`src/osm/gaps.py`) with a 30 m proximity threshold and 5 m
junction clustering.

## Rider-impact detectors

Eight detectors operate over the harvested ways, nodes, and relations.
These surface defects independently of TIGER provenance:

| Detector | Predicate | Routing impact (1–5) |
|---|---|---|
| `oneway_minus_one` | `oneway=-1` on a Class A highway type | 4 |
| `oneway_conflicts` | same-name parallel ways with same-direction `oneway`; lateral-vs-longitudinal-offset filter excludes legitimate divided carriageways | 5 |
| `access_blocked_residential` | `access` ∈ {`no`, `private`} on `highway=residential`, excluding `motor_vehicle=destination` (gated communities) | 5 |
| `barriers_without_access` | `barrier` ∈ {`gate`, `bollard`, `lift_gate`, `swing_gate`, `cycle_barrier`} with no access qualifier | 4 |
| `broken_turn_restrictions` | `relation[type=restriction]` missing `from` / `via` / `to` member, or empty `restriction` tag | 4 |
| `arterial_named_residential` | `highway=residential` whose name terminates in Boulevard / Parkway / Expressway / Pike / Highway / Crossing / Memorial | 3 |
| `missing_maxspeed_arterial` | `highway` ∈ {tertiary, unclassified} without `maxspeed` | 3 |
| `misplaced_bus_stops` | `highway=bus_stop` whose nearest drivable-way vertex exceeds 20 m, after cross-checking against SORTA GTFS stop positions | 2 |

Each finding carries an explicit `routing_impact` score; the Atlas UI
surfaces them in an inventory panel sorted by impact descending.

## Conflation against ground truth

`src/osm/conflate.py` matches every harvested OSM way against the
nearest Cincinnati Area GIS centerline using a three-term weighted
score:

```
confidence = 0.5 · name_similarity      (Ratcliff-Obershelp on normalized names)
           + 0.3 · geometry_overlap     (1 − directed-Hausdorff/30 m, OSM→CAGIS only)
           + 0.2 · direction_alignment  (|cos θ| between line direction vectors)
```

The geometry term uses **directed** Hausdorff (max-over-OSM-points
of min-distance-to-CAGIS). The symmetric form blew up on the common
topology where OSM has a long named street broken into shorter ways
at intersections — see [`docs/explainers/conflation-matcher.md`](docs/explainers/conflation-matcher.md).

Three confidence bands gate downstream behavior:

- `confidence ≥ 0.85` → **auto-submit eligible**: CAGIS `TRVL_DIR`
  overrides OSM `oneway`, CAGIS `SPEEDLIMIT` supplies a missing
  `maxspeed`, CAGIS `STRLABEL` flags a name mismatch (always queued
  for human review — CAGIS uses postal abbreviations, OSM convention
  is spelled-out names).
- `0.6 ≤ confidence < 0.85` → **human-review queue**: surfaced as a
  candidate, never auto-submitted.
- `confidence < 0.6` → match dict still attached to the way but
  filtered out of both submit and review queues; the
  `diagnose_match()` baseline pass classifies these into F1–F4 /
  MIXED_LOW for matcher tuning.

The nearest-neighbor fallback (when STRtree returns no candidates
within 30 m) is hard-capped at `REVIEW_CONFIDENCE` — fallback hits
populate human review but never auto-submit.

## Service zones

| Zone key | Communities served |
|---|---|
| `blue-ash-montgomery` | Blue Ash, Montgomery, Deer Park, Silverton, Kenwood, Madeira |
| `springdale-sharonville` | Springdale, Sharonville, Glendale, Evendale, Lincoln Heights |
| `northgate-mt-healthy` | Mt. Healthy, North College Hill, Finneytown, Northgate |
| `forest-park-pleasant-run` | Forest Park, Pleasant Run, Greenhills |

Zone polygons are extracted from SORTA's published web map and stored
under [`src/osm/zones/<zone-key>.geojson`](src/osm/zones/); see
[`docs/explainers/zone-data-flow.md`](docs/explainers/zone-data-flow.md)
for why the bbox-and-polygon split is load-bearing (Forest Park's bbox
bleeds 1 km north into Butler County, producing 78% F1 pre-clip).

## Quickstart

Requires Python 3.12+ and Node.js 20+. Shapely 2.0+ is required for
conflation; if absent, the rest of the pipeline still runs and
conflation degrades to a no-op with a warning.

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
osm preflight --zone blue-ash-montgomery               # 17 readiness checks
osm fix --zone blue-ash-montgomery --dry-run           # preview corrections
osm fix --zone blue-ash-montgomery                     # submit changesets
osm auth login                                         # OSM OAuth 2.0 + PKCE
```

The full subcommand reference (17 commands across 6 lifecycle stages)
lives in [`docs/cli-reference.md`](docs/cli-reference.md).

## Compliance and provenance

Every changeset must comply with the OSM
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct):

- Edits must be documented in advance on a wiki page (the changeset's
  `description` tag links to it).
- Discussion on `talk-us@` and `community.openstreetmap.org` is
  required, with a 14-day comment window before bulk runs.
- Changesets are tagged `mechanical=yes`, `bot=yes`, and carry the
  project source attribution.
- Opt-out requests are honored immediately.
- Changesets stay well below the 10,000-element CGImap limit; the
  project default is ≤ 500 elements per batch to keep diff review
  tractable in OSMCha.

CAGIS data is used "as is" per the Open Data Hub license; attribution
is written into every CAGIS-sourced changeset via the
`cagis:attribution` tag. The four-step Phase 1 community-gating
sequence (Minh outreach → `_cincyimport` account → wiki page →
talk-us@ post + 14-day window) is documented in detail in
[`docs/explainers/osm-community-gating.md`](docs/explainers/osm-community-gating.md);
paste-ready drafts live under [`docs/community-prep/`](docs/community-prep/).

## Project documentation

Three layered surfaces, each with its own template and audience:

- **[`CLAUDE.md`](CLAUDE.md)** — dense context manifest. Source of
  truth for architecture, conventions, phase status. Optimized for
  fast loading by AI sessions.
- **[`docs/explainers/`](docs/explainers/)** — 13 hand-written
  decompression docs for the dense `CLAUDE.md` sections. Each follows
  the same template (summary → bridge steps → load-bearing Mermaid →
  `file:line` citations). Topics: detector taxonomy, conflation
  matcher, OSM community gating, phase status, zone data flow,
  routing engine dispatch, conventions, OAuth + PKCE flow, history
  filter, pre-flight checks, MapRoulette tasks, Transit App quota,
  external feeds.
- **[`docs/skills/`](docs/skills/)** — 14 explainers for the
  `.claude/skills/` directory. Short, skim-friendly companions to
  each `SKILL.md` for re-entry.

Plus codebase-area overviews:

- [`docs/cli-reference.md`](docs/cli-reference.md) — 17 `osm`
  subcommands grouped by lifecycle stage.
- [`docs/tests-overview.md`](docs/tests-overview.md) — pytest layout,
  what's tested vs deliberately not, how to add a test.
- [`docs/web-architecture.md`](docs/web-architecture.md) — Express
  server + vanilla SPA + shell-out-to-Python design.
- [`docs/sources.md`](docs/sources.md) — external-source evaluation
  log (active, defensive backups, bookmarks, ruled-out).

## Background

Successor to [AICincy/Tiger](https://github.com/AICincy/Tiger),
which detected defects via the now-deprecated `tiger:reviewed=no`
filter. Per community feedback from
[Minh Nguyễn](https://wiki.openstreetmap.org/wiki/User:Mxn), that
tag is unreliable in both directions: cleanup bots strip it without
fixing the geometry, and human mappers leave it in place after
correcting the data. This pipeline replaces the single-tag heuristic
with a union query (TIGER origin marker ∪ defect signature), layered
with eight rider-impact detectors that operate independently of
TIGER provenance, and grounded against CAGIS Street Centerlines for
verifiable mechanical fixes.

[`RESEARCH-FINDINGS.md`](RESEARCH-FINDINGS.md) holds the full
investigation into Via's data architecture, the TIGER defect
taxonomy, the OSM API v0.6 constraints, and the OSM community
process requirements. Read it before opening a PR that changes the
defect detectors or the changeset submission path.

## See also

- [`CLAUDE.md`](CLAUDE.md) — project context manifest.
- [`docs/explainers/detector-taxonomy.md`](docs/explainers/detector-taxonomy.md) — the dual-track classifier vs detector design.
- [`docs/explainers/conflation-matcher.md`](docs/explainers/conflation-matcher.md) — directed-Hausdorff scoring + asymmetric-promotion alert.
- [`docs/explainers/osm-community-gating.md`](docs/explainers/osm-community-gating.md) — the four-step Phase 1 gating in dependency order.
- [`docs/cli-reference.md`](docs/cli-reference.md) — every `osm` subcommand.
- [Open data attribution]: data © OpenStreetMap contributors (ODbL); data © Cincinnati Area GIS / Hamilton County, Ohio (Open Data Hub).

## License

[MIT](LICENSE).
