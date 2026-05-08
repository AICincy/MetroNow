# Contributing

This pipeline mutates a public, community-governed geographic database. Read
[`README.md`](README.md) and [`RESEARCH-FINDINGS.md`](RESEARCH-FINDINGS.md)
before contributing — the latter documents the OSM API constraints, the
TIGER defect taxonomy, and the OSM community process requirements that any
PR touching the changeset path must respect.

## Setup

Prerequisites:

- Python 3.12+
- Node.js 20+

Install the Python package in editable mode with development dependencies:

```bash
pip install -e ".[dev]"
```

The `[dev]` extra brings in `pytest` and `pytest-cov`. The runtime
dependencies are `requests`, `httpx`, `openpyxl`, `click`, `rich`, and
`shapely>=2.0`. Shapely 2 includes the STRtree spatial index used by
`osm.conflate`; if the install fails on your platform, conflation will
degrade to a no-op with a warning and the rest of the pipeline still
operates.

Install the web frontend dependencies:

```bash
cd web && npm install
```

## OAuth credential setup

Submitting corrections to OSM requires API v0.6 OAuth 2.0 credentials. OAuth
1.0a was sunset in June 2024.

1. Sign in at [openstreetmap.org](https://www.openstreetmap.org).
2. Visit [My Settings → OAuth 2 applications](https://www.openstreetmap.org/oauth2/applications).
3. Register a new application:
   - Redirect URI: `urn:ietf:wg:oauth:2.0:oob`
   - Scopes: `write_api`, `read_prefs`
4. Write the credentials to `~/.config/osm/credentials.json`:

```json
{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET"
}
```

The token is stored at `~/.config/osm/token.json` after `osm auth login`.
See `.env.example` for optional environment-variable overrides.

## Operating the pipeline

```bash
osm scan --zone blue-ash-montgomery                    # standard scan: harvest + classify + detect + report
osm scan --zone blue-ash-montgomery --skip-history     # skip per-way revision-history fetch
osm scan --zone blue-ash-montgomery --with-conflation  # add CAGIS Street Centerlines ground truth
osm scan --zone blue-ash-montgomery --import-only      # opt-in: only ways still on original TIGER import (small, definite)
osm scan --zone all                                    # all four MetroNow zones sequentially
osm conflate --zone blue-ash-montgomery                # conflate against existing scan-results.json (no re-fetch)
osm fix --zone blue-ash-montgomery --dry-run           # preview proposed corrections without submitting
osm fix --zone blue-ash-montgomery                     # submit batched changesets
osm auth login                                         # OAuth 2.0 + PKCE login
osm auth status                                        # show stored token info
```

The web dashboard is started separately:

```bash
cd web && npm start
```

It serves the MetroNow Atlas UI at `http://localhost:3000` and exposes a REST
API the frontend consumes. The previous (pre-redesign) UI is preserved under
`web/public/.legacy/` for rollback or reference.

## Testing

```bash
pytest tests/ -v          # full test suite (262 tests at HEAD)
ruff check src/           # lint Python sources
mypy src/osm/ --ignore-missing-imports
cd web && npx eslint@8 public/js/atlas.js public/js/atlas-extras.js \
  --no-eslintrc --env es2020 --env browser \
  --rule '{"no-undef":"off","no-unused-vars":"warn"}'
```

CI (`.github/workflows/ci.yml`) runs all four against Ubuntu on Python 3.12
and 3.13. Every PR must keep all four green.

## Project structure

```
src/osm/
  cli.py                Click CLI: scan, fix, auth, conflate, report subcommands
  fetch.py              Overpass union query (way + relation + node) with retry, mirror, cache
  classify.py           Class A/B/AB/C taxonomy + dispatch to rider-impact detectors
  detectors.py          Eight rider-impact detectors (non-TIGER): oneway-`-1`,
                        oneway conflicts, access-blocked residential, unqualified
                        barriers, broken turn restrictions, arterial-named residential,
                        missing arterial maxspeed, misplaced bus stops
  gaps.py               Haversine-based node-disconnect detection with junction clustering
  geo.py                Haversine, valid lat/lon, name normalization
  history.py            OSM API v0.6 way/node revision-history fetch with caching
  history_filter.py     Two-tier review-status determination (metadata + history)
  polygons.py           Hamilton County polygon clip + per-zone polygon clip
                        (real MetroNow operational polygons, sourced from
                        SORTA's published web map). Drops elements outside
                        the polygon centroid post-fetch.
  conflate.py           Shapely STRtree match against CAGIS Street Centerlines.
                        Directed Hausdorff (OSM→CAGIS) for the geometry term;
                        nearest-neighbor fallback inside FALLBACK_BUFFER_M caps
                        confidence at REVIEW_CONFIDENCE so it never auto-submits.
                        diagnose_match() / write_baseline_manifest() emit a
                        per-way bucket-attribution JSON (MATCHED_HIGH /
                        MATCHED_REVIEW / MATCHED_FALLBACK_REVIEW / F1-F4 / MIXED)
                        used for matcher tuning.
  tiger2024.py          Fallback ground truth: Census TIGER/Line 2024 county roads
                        (only consulted for ways CAGIS doesn't cover)
  notes.py / osmose.py  Read-only feeds — OSM Notes (community feedback) and
                        Osmose quality-issue badges shown in the inventory and
                        Investigations panels, never auto-submitted
  gtfs.py               SORTA GTFS stops loader, used by misplaced_bus_stops to
                        suppress off-curb-shelter false positives that match a
                        published stop position
  route_diff.py         BRouter route-diff harness — graduates rider-impact
                        detector hits to "real / inconclusive / noisy" by
                        perturbing the routing graph and comparing routes
  review.py             proposed_fix(es)_for_way: classifier and CAGIS-verified fix kinds
  changeset.py          OSM API v0.6 changeset creation, batching, diff upload
  auth.py               OAuth 2.0 Authorization Code + PKCE
  config.py             Endpoints, paths, thresholds, TIGER import users/dates, wiki URL
  zones.py              MetroNow service-zone bbox definitions
  cache.py              Generic disk-cache helpers (TTL prune, newest-N retention)
  csv_export.py         Four sorted CSV slices (per scan)
  xlsx.py               Eight-sheet openpyxl workbook
  dashboard.py          Self-contained Leaflet HTML dashboard

web/
  server.js             Express REST API; /api/{auth,zones,scan,results,review,fix,
                        reports,dashboard,history,export,conflate}
  public/index.html     MetroNow Atlas single-page UI
  public/js/atlas.js          Main app logic
  public/js/atlas-extras.js   Theme/density/accent/weight tweaks
  public/css/atlas-supplement.css
  public/.legacy/             Pre-redesign UI (preserved)

tests/
  test_classify.py      A/B/AB/C classification logic
  test_geo.py           Haversine, valid_latlon, norm_name
  test_gaps.py          Gap detection + junction clustering
  test_history_filter.py Tier-1 / Tier-2 review-status assignment
  test_review.py        proposed_fix and proposed_fixes_for_way
  test_detectors.py     All eight rider-impact detectors (positive + negative cases)
  test_conflate.py      Shapely match scoring, fallback path, F1-F4 bucket
                        attribution, baseline manifest round-trip, graceful
                        Shapely-missing degradation
  test_notes.py         OSM Notes feed parser + zone filter
  test_osmose.py        Osmose API parser + zone filter
  test_route_diff.py    BRouter perturbation harness (real / noisy / inconclusive)
  test_tiger2024.py     TIGER/Line 2024 fallback conflation

docs/
  metronow-atlas.html   UI redesign reference
  change-log.html       Editorial change log
  independent-audit.html  Independent audit report

.github/workflows/ci.yml  Python (matrix 3.12, 3.13) + Node lint
```

## PR conventions

- Branch names use hyphens: `fix-oneway-detection`, never `fix_oneway_detection`.
- Commit messages explain the **why**; the diff already shows the what.
- Run the full test, lint, and type-check trio locally before pushing.
- Keep PRs focused on one logical change. A detector tightening, a CAGIS
  field-mapping change, and a UI tweak are three PRs, not one.
- Touching the changeset submission path requires a corresponding update to
  the OSM wiki page documenting this audit, and a heads-up on `talk-us@` if
  the change affects what gets submitted (not just how).

## OSM community compliance

All automated edits to OpenStreetMap must comply with the
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct).
The pipeline enforces the mechanical attributes:

- Every changeset carries `mechanical=yes`, `bot=yes`, `created_by=...`,
  `source=survey;CAGIS Open Data Hub`, and `description=<wiki URL>`.
- Every CAGIS-sourced fix additionally writes `cagis:attribution` to satisfy
  the CAGIS Open Data Hub license terms.
- The default per-changeset batch size is 500 elements (`changeset.py:
  CHANGESET_BATCH_SIZE`); the production CGImap hard limit is 10,000.
- The pipeline does not bypass review: it produces fix descriptors and
  XML-diff payloads, but the operator is responsible for opening the
  pre-edit wiki page, posting on `talk-us@` for novel zones, and honoring
  opt-out requests immediately after they appear.

## Scope discipline

The pipeline is for the four MetroNow zones in Hamilton County, OH. It is
not a general-purpose OSM editor. Pull requests broadening the scope to
arbitrary geographies should expect to be redirected to MapRoulette or to a
fork. Pull requests that improve detector precision, conflation match rate,
ground-truth integration with ODOT TIMS or the Hamilton County Auditor
parcel layer, or rider-experience telemetry, are welcome.
