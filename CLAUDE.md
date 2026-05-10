# MetroNow

OSM road defect detection and correction for Hamilton County MetroNow
microtransit zones. Via Transportation's ViaMapping routing layer is built on
OpenStreetMap — corrections submitted here propagate, on Via's next ingest, to
the routing tiles that ViaAlgo consumes for every MetroNow trip.

## Layout

- `src/osm/` — Python package (pip-installable as `osm`)
  - Pipeline: `fetch.py`, `polygons.py`, `classify.py`, `detectors.py`,
    `gaps.py`, `history.py`, `history_filter.py`, `conflate.py`,
    `review.py`, `changeset.py`
  - External feeds: `gtfs.py` (SORTA GTFS stops cross-check, with
    Mobility Database catalog lookup mdb-366 for the feed URL),
    `bus_routes.py` (CAGIS METRO Bus Routes — transit-corridor
    corroboration for oneway_conflict findings), `transit.py`
    (Transit App API client, rate-limit + monthly-quota aware,
    `fcntl.flock`-guarded counter), `notes.py` (OSM Notes),
    `osmose.py` (Osmose quality issues)
  - Routing: `route_diff.py` (BRouter, default), `motis.py`
    (MOTIS `/api/v5/plan` prototype, opt-in via `MOTIS_BASE` env;
    `is_available()` probe; matches `route_diff.fetch_route` shape
    so the future swap is one dispatcher line)
  - Operational: `preflight.py` (codified first-changeset readiness
    gate; 16 checks across 6 categories with PASS/FAIL/WARN/MANUAL)
  - Zone polygons: `src/osm/zones/<zone-key>.geojson` (real MetroNow
    operational polygons from SORTA's web map) + `hamilton-county.geojson`
    (TIGER FIPS 39061 fallback)
  - Output: `xlsx.py`, `dashboard.py`, `csv_export.py`
  - Plumbing: `cli.py` (Click), `config.py`, `zones.py`, `geo.py`,
    `cache.py`, `auth.py` (OAuth 2.0 + PKCE)
- `web/` — Express.js server + vanilla HTML/CSS/JS frontend (MetroNow Atlas
  redesign)
  - `web/server.js` — REST API on port 3000, shells out to Python via
    `child_process`
  - `web/public/index.html` — single-page UI with overlay panels (Inventory,
    Fix, Ledger, Discuss, Account)
  - `web/public/js/atlas.js` — main app logic
  - `web/public/js/atlas-extras.js` — theme/density/accent/weight tweaks
  - `web/public/css/atlas-supplement.css` — components added by atlas.js
  - `web/public/.legacy/` — original UI preserved for rollback
- `tests/` — pytest suite (**372 passing** as of `9836bb9`)
- `osm-audit-{zone}/` — generated outputs per zone (gitignored): raw Overpass
  cache under `data/`, `scan-results.json`, `reports/`, `csv/`
- `docs/community-prep/01-05.md` — paste-ready community-gating drafts
- `docs/motis-deployment.md` — honest stand-up notes for the MOTIS prototype

## Paths

- Python: auto-detected from PATH (`python3` or `python`)
- Node: `C:\Program Files\nodejs\node.exe`
- Web server: `node web/server.js` (localhost:3000)
- OAuth: OOB redirect (`urn:ietf:wg:oauth:2.0:oob`), credentials at
  `~/.config/osm/credentials.json`, token at `~/.config/osm/token.json`
- CAGIS conflation cache: `~/.config/osm/cagis_cache/centerlines-{hash}.geojson`
  (90-day TTL)
- History cache: `~/.config/osm/history_cache/` (7-day TTL)

## Conventions

- File names use hyphens, never underscores
- No CLI instructions to the user — run everything directly
- Auto mode is the default — make decisions, don't present menus
- Audit work before declaring done — verify at module boundaries (fetch
  output feeds classify, classify output feeds reports, classify output
  feeds conflation, review output feeds changeset) and spot-check outputs
  against known data before signing off
- Path construction in `web/server.js` MUST go through `zonePath()` so
  the resolved-prefix containment guard runs at every site (CodeQL
  js/path-injection hygiene)
- Concurrent file mutators (e.g. transit usage counter) hold an
  exclusive `fcntl.flock` on POSIX — falls back to unlocked write when
  fcntl is unavailable
- Strict CSP via helmet is required; the allow-list mirrors the
  external origins in `web/public/index.html` (unpkg, CARTO, Esri,
  OSM tile servers, Nominatim) and `script-src` never includes
  `'unsafe-inline'`

## OSM community requirements

- Mechanical edits require wiki documentation, `talk-us@` discussion, and
  `_cincyimport`-convention account
- Changeset community norm is ~500 elements (CGImap hard limit 10,000)
- Use MapRoulette for corrections with >5% expected false-positive rate
- Active ground truth: CAGIS quarterly centerlines (FeatureServer/26),
  TIGER/Line 2024 county roads as a fallback layer (`src/osm/tiger2024.py`)
- Aspirational ground truth (not yet integrated; do not cite in `source=`
  tags until a working endpoint is wired): ODOT TIMS
- Every CAGIS-sourced changeset must carry the `cagis:attribution` tag per
  the Open Data Hub license

## Detector taxonomy

Two parallel tracks. Both run in `classify()`; the second only emits to the
"Rider-impact findings" panel — never to the mechanical-fix queue. See
[`docs/explainers/detector-taxonomy.md`](docs/explainers/detector-taxonomy.md)
for the decompressed version with diagram and code citations.

- **Classifier (TIGER-fixup heuristic, mechanical-fix candidates):** Class
  A, AB, B, C; node-disconnect gaps. Defined in `classify.py` and `gaps.py`.
- **Detectors (rider-impact, human-review only):** eight detectors in
  `detectors.py` covering oneway-`-1`, parallel oneway conflicts, blocked
  residential access, unqualified barriers, broken turn restrictions,
  arterial-named residentials, missing arterial maxspeeds, misplaced bus
  stops.

Mechanical fixes from CAGIS conflation supplement the classifier track only,
not the detector track.

## Conflation matcher state

CAGIS centerline conflation lives in `src/osm/conflate.py`. Tunings
that survived data-driven validation:

- **Directed Hausdorff (OSM→CAGIS only)**, not symmetric — F3
  ("geometry fail") was 70.5% of misses with symmetric because OSM
  fragments are legitimate sub-segments of longer CAGIS centerlines.
  Switching to the directed form lifted auto-submit 5.0% → 12.1%.
- Three-term scoring: `W_NAME=0.5 + W_GEOMETRY=0.3 + W_DIRECTION=0.2`,
  thresholds `BUFFER_M=30.0`, `HIGH_CONFIDENCE=0.85`,
  `REVIEW_CONFIDENCE=0.6`, `FALLBACK_BUFFER_M=100.0`
- Nearest-neighbor fallback is hard-capped at `REVIEW_CONFIDENCE` —
  it can populate the human-review band, never the auto-submit pool
- Diagnostics: F1–F4 bucket attribution (`NO_CANDIDATE`, `NAME_FAIL`,
  `GEOMETRY_FAIL`, `DIRECTION_DRAG`); `osm baseline-diff --zone <key>`
  flags asymmetric-promotion violations between matcher runs
- Match rate across 4 zones: 22.76–26.40%; auto-submit pool 2,043
  ways

## Phase status (as of 2026-05-08 EOD, commit `9836bb9`)

- **Phase 1 (community gating)** — ⏳ blocked on human action.
  All five `docs/community-prep/*.md` drafts ready; Transit-App ToS
  compliance email **sent** to Richard at Transit App (awaiting
  reply on quota uplift). Wiki / talk-us@ / community.osm.org
  publication still pending. Minh Nguyễn outreach is now warm via
  direct technical correspondence (directed-Hausdorff matcher,
  MOTIS prototype). `_cincyimport`-convention account not yet
  created.
- **Phase 2, 3, 4** — ✅ complete; matcher fixes shipped, MapRoulette
  generators shipped, polygon-clip / route-diff / detector hardening
  shipped.
- **MOTIS prototype** — ✅ shipped at `src/osm/motis.py` plus
  `osm motis-status`; opt-in via `MOTIS_BASE` env; pipeline
  silently degrades to BRouter when MOTIS isn't reachable. Engine
  dispatcher in `route_diff.py` is the next-session item.
- **Pre-flight automation** — ✅ `osm preflight --zone <key>` runs
  16 checks; FAIL/WARN/MANUAL exit codes; `--strict` escalates WARN.
- **Transit App quota tooling** — ✅ `osm transit-status`,
  `osm transit-budget [--calls N]`. Concurrent-safe usage counter
  via `fcntl.flock`. The required attribution `"Powered by Transit"`
  ships verbatim in the Atlas footer.
- **CodeQL alerts** — #4, #6–10, #17, #24 fixed in code; #3
  (auth.py:120 OAuth URL print) flagged for "won't fix / false
  positive" UI dismissal — by RFC 6749 §4.1.1 the URL contains no
  actual secrets.

## Operator identity context

The maintainer is a transit rider, taxpayer, disabled citizen, civil
rights activist, enterprise GIS professional, and Login.gov-credentialed
US Government GIS Volunteer. The Transit-App ToS-compliance email and
talk-us@ post lean on this regulatory perimeter (49 CFR Parts 21, 27,
37, 38; § 37.169 demand-responsive equivalent service; FTA Circulars
4710.1 + 4702.1B; EO 12898 + EO 13166). Paid-tier options are off the
table — leverage civic angle, not budget.
