# MetroNow

**Summary.** OSM road-defect detection and correction pipeline for the
four Hamilton County zones served by SORTA's [MetroNow](https://www.go-metro.com/metronow)
on-demand microtransit service. Via Transportation's ViaMapping
routing layer is built on OpenStreetMap: defects in OSM propagate,
on Via's next ingest, into the routing tiles every MetroNow trip
relies on. The pipeline harvests candidate defects from Overpass,
classifies them with a TIGER-fixup taxonomy, ground-truths a subset
against the Cincinnati Area GIS (CAGIS) Open Data Hub, and submits
verifiable corrections back to OSM via OAuth 2.0 changesets with
full community compliance.

---

## What this is

The 2007-2008 TIGER/Line bulk import (`DaveHansenTiger`) seeded a
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
    UI["Atlas UI<br/>Rider-impact findings panel"]
    Detectors --> UI
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
perimeter: see [`docs/explainers/detector-taxonomy.md`](docs/explainers/detector-taxonomy.md).

## Defect taxonomy (classifier track)

```mermaid
---
title: "How an OSM way lands in Class A / AB / B / C"
---
flowchart TD
    Way["OSM way<br/>(highway in residential / unclassified /<br/>tertiary / service)"]
    OnewayQ{"oneway truthy?<br/>(yes / true / 1 / -1)"}
    NameQ{"shares normalized name<br/>with ≥1 other way in zone?"}
    NameQ2{"shares normalized name<br/>with ≥1 other way in zone?"}

    AB["Class AB: CRITICAL<br/>oneway + multi-segment<br/>(compound defect, highest routing impact)"]
    A["Class A: CRITICAL<br/>oneway, no multi-segment"]
    B["Class B: HIGH<br/>multi-segment, no oneway<br/>(disconnect risk via gaps.py:<br/>30 m threshold + 5 m clustering)"]
    C["Class C: LOW<br/>no immediate defect signal"]

    Way --> OnewayQ
    OnewayQ -- yes --> NameQ
    OnewayQ -- no --> NameQ2
    NameQ -- yes --> AB
    NameQ -- no --> A
    NameQ2 -- yes --> B
    NameQ2 -- no --> C

    classDef critical fill:#5b1c1c,stroke:#a04040,color:#f8e0e0,font-weight:bold
    classDef high fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    classDef low fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    class AB,A critical
    class B high
    class C low
```

The classifier emits one terminal class per way. Class B's
multi-segment grouping additionally feeds haversine-based
node-disconnect detection in `src/osm/gaps.py` (30 m proximity
threshold, 5 m junction clustering). See
[`docs/explainers/detector-taxonomy.md`](docs/explainers/detector-taxonomy.md)
for the full classifier-vs-detector decomposition.

## Rider-impact detectors

Eight detectors operate over the harvested ways, nodes, and relations.
Each finding carries a `routing_impact` score (1 = noise; 5 = blocks
an arterial-class route). The detectors are independent: one broken
detector cannot kill the audit run thanks to the `_safe_run` wrapper
in `classify.py`.

```mermaid
---
title: "Eight rider-impact detectors grouped by routing impact (5 = highest)"
---
flowchart LR
    subgraph Impact5["routing_impact = 5<br/>(blocks an arterial-class route)"]
        direction TB
        D5a["oneway_conflicts<br/>same-name parallel ways with<br/>same-direction oneway;<br/>lateral-vs-longitudinal filter<br/>excludes divided carriageways"]
        D5b["access_blocked_residential<br/>access in {no, private} on<br/>highway=residential, excluding<br/>motor_vehicle=destination<br/>(gated communities)"]
    end

    subgraph Impact4["routing_impact = 4<br/>(degrades routing materially)"]
        direction TB
        D4a["oneway_minus_one<br/>oneway=-1 on a Class A<br/>highway type"]
        D4b["barriers_without_access<br/>barrier in {gate, bollard,<br/>lift_gate, swing_gate,<br/>cycle_barrier} without<br/>access qualifier"]
        D4c["broken_turn_restrictions<br/>relation[type=restriction]<br/>missing from / via / to<br/>member, or empty<br/>restriction tag"]
    end

    subgraph Impact3["routing_impact = 3<br/>(misclassifies highway type)"]
        direction TB
        D3a["arterial_named_residential<br/>highway=residential whose<br/>name ends in Boulevard /<br/>Parkway / Expressway / Pike /<br/>Highway / Crossing / Memorial"]
        D3b["missing_maxspeed_arterial<br/>highway in {tertiary,<br/>unclassified} without<br/>maxspeed"]
    end

    subgraph Impact2["routing_impact = 2<br/>(rider-facing but soft)"]
        direction TB
        D2["misplaced_bus_stops<br/>highway=bus_stop whose<br/>nearest drivable vertex > 20 m,<br/>cross-checked against<br/>SORTA GTFS stop positions"]
    end

    classDef sev5 fill:#5b1c1c,stroke:#a04040,color:#f8e0e0
    classDef sev4 fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    classDef sev3 fill:#3a3a1c,stroke:#888866,color:#eeeec0
    classDef sev2 fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    class Impact5,D5a,D5b sev5
    class Impact4,D4a,D4b,D4c sev4
    class Impact3,D3a,D3b sev3
    class Impact2,D2 sev2
```

The Atlas UI surfaces findings in an inventory panel sorted by
`routing_impact` descending. None of these are auto-submitted: they
require human review and (for findings exceeding 5% expected
false-positive rate) optionally a MapRoulette challenge for
community triage.

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
at intersections: see [`docs/explainers/conflation-matcher.md`](docs/explainers/conflation-matcher.md).

```mermaid
---
title: "Confidence bands → downstream treatment"
---
flowchart LR
    Score["confidence score<br/>0.5·name + 0.3·geom + 0.2·dir"]

    HIGH["MATCHED_HIGH<br/>≥ 0.85<br/>auto-submit eligible"]
    REVIEW["MATCHED_REVIEW<br/>0.6 ≤ conf < 0.85<br/>human-review queue"]
    LOW["confidence &lt; 0.6<br/>filtered out of submit + review<br/>diagnose_match → F1 through F4 / MIXED_LOW"]
    FALLBACK["MATCHED_FALLBACK_REVIEW<br/>fallback path (within 100m)<br/>capped at 0.6: never auto-submits"]

    Score -- "in-buffer (≤30m), conf ≥ 0.85" --> HIGH
    Score -- "in-buffer, 0.6 ≤ conf < 0.85" --> REVIEW
    Score -- "in-buffer, conf < 0.6" --> LOW
    Score -- "out-of-buffer fallback" --> FALLBACK

    HIGH -- "set TRVL_DIR<br/>+ SPEEDLIMIT<br/>+ STRLABEL (review)" --> Submit(("changeset.py<br/>auto-submit"))
    REVIEW --> Triage(("Atlas Fix panel<br/>human review"))
    FALLBACK --> Triage
    LOW --> Diagnostic(("baseline-diff<br/>tuning only"))

    classDef safe fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    classDef judgment fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    classDef gate fill:#3a3a3a,stroke:#888,color:#eee
    class HIGH,Submit safe
    class REVIEW,FALLBACK,Triage judgment
    class LOW,Diagnostic gate
```

The nearest-neighbor fallback (when STRtree returns no in-buffer
candidates) is hard-capped at `REVIEW_CONFIDENCE`: fallback hits
populate human review but **never** auto-submit. This is the
project's epistemic gate: any edit submitted to OSM as a mechanical
edit must clear 0.85 against an authoritative external source.

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
bleeds 1 km north into Butler County, producing a 78%
`F1_NO_CANDIDATE` rate pre-clip — these are ways with no CAGIS
match because CAGIS coverage stops at the county line, not because
the OSM geometry was wrong).

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

```mermaid
---
title: "Documentation surfaces — what's where, by reader"
---
flowchart TD
    Reader["Reader<br/>(future-you / fresh AI session /<br/>OSM admin / curious newcomer)"]

    CLAUDE["CLAUDE.md<br/>dense context manifest<br/>(fast-loading for AI sessions)"]
    Glossary["docs/glossary.md<br/>color-coded terms / tags /<br/>sources / workflow"]

    subgraph Decompress["docs/explainers/: 13 decompression docs"]
        direction TB
        DT["detector-taxonomy<br/>conflation-matcher<br/>osm-community-gating<br/>phase-status<br/>zone-data-flow<br/>routing-engine-dispatch<br/>conventions<br/>oauth-pkce-flow<br/>history-filter<br/>preflight-checks<br/>maproulette-tasks<br/>transit-quota<br/>external-feeds"]
    end

    subgraph Skills["docs/skills/: 14 skill explainers"]
        direction TB
        SK["zone-audit / cagis-conflate /<br/>ground-truth-diff / tiger-history-deep /<br/>osmcha-monitor / community-prep /<br/>changeset-submit / maproulette-challenge /<br/>metronow-{code,javascript,html,css,dockerfile}-review /<br/>metronow-explainer"]
    end

    subgraph Codebase["docs/: codebase-area overviews"]
        direction TB
        OV["cli-reference (17 osm subcommands)<br/>tests-overview (pytest layout)<br/>web-architecture (Express + SPA)<br/>sources (external-feed evaluation log)"]
    end

    subgraph Community["docs/community-prep/: paste-ready drafts"]
        direction TB
        CP["00-README<br/>01-wiki-page<br/>02-talk-us-post<br/>03-minh-outreach<br/>04-pre-flight-checklist<br/>05-transit-api-compliance"]
    end

    Reader --> CLAUDE
    Reader --> Glossary
    CLAUDE -. "cross-links to" .-> Decompress
    CLAUDE -. "cross-links to" .-> Codebase
    Decompress -. "cross-links to" .-> Skills
    Glossary -. "anchors terms in" .-> Decompress
    Decompress -. "Phase 1 chain" .-> Community

    classDef manifest fill:#3a3a3a,stroke:#888,color:#eee,font-weight:bold
    classDef anchor fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    classDef detail fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    class CLAUDE manifest
    class Glossary anchor
    class Decompress,Skills,Codebase,Community,DT,SK,OV,CP detail
```

Three layered surfaces, each with its own template and audience:

- **[`CLAUDE.md`](CLAUDE.md)**: dense context manifest. Source of
  truth for architecture, conventions, phase status. Optimized for
  fast loading by AI sessions.
- **[`docs/explainers/`](docs/explainers/)**: 13 hand-written
  decompression docs for the dense `CLAUDE.md` sections. Each follows
  the same template (summary → bridge steps → load-bearing Mermaid →
  `file:line` citations). Topics: detector taxonomy, conflation
  matcher, OSM community gating, phase status, zone data flow,
  routing engine dispatch, conventions, OAuth + PKCE flow, history
  filter, pre-flight checks, MapRoulette tasks, Transit App quota,
  external feeds.
- **[`docs/skills/`](docs/skills/)**: 14 explainers for the
  `.claude/skills/` directory. Short, skim-friendly companions to
  each `SKILL.md` for re-entry.

Plus codebase-area overviews:

- [`docs/cli-reference.md`](docs/cli-reference.md): 17 `osm`
  subcommands grouped by lifecycle stage.
- [`docs/tests-overview.md`](docs/tests-overview.md): pytest layout,
  what's tested vs deliberately not, how to add a test.
- [`docs/web-architecture.md`](docs/web-architecture.md): Express
  server + vanilla SPA + shell-out-to-Python design.
- [`docs/sources.md`](docs/sources.md): external-source evaluation
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

- [`CLAUDE.md`](CLAUDE.md): project context manifest.
- [`docs/glossary.md`](docs/glossary.md): every project-specific
  term, OSM tag, authoritative source, and workflow concept,
  color-coded by category (🔴 critical / 🟡 review / 🟢 ground-truth /
  🔵 declarative / ⚪ informational).
- [`docs/explainers/detector-taxonomy.md`](docs/explainers/detector-taxonomy.md): the dual-track classifier vs detector design.
- [`docs/explainers/conflation-matcher.md`](docs/explainers/conflation-matcher.md): directed-Hausdorff scoring + asymmetric-promotion alert.
- [`docs/explainers/osm-community-gating.md`](docs/explainers/osm-community-gating.md): the four-step Phase 1 gating in dependency order.
- [`docs/cli-reference.md`](docs/cli-reference.md): every `osm` subcommand.
- **Open data attribution:** data © OpenStreetMap contributors (ODbL); data © Cincinnati Area GIS / Hamilton County, Ohio (Open Data Hub).

## License

[MIT](LICENSE).
