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
  - External feeds: `gtfs.py` (SORTA GTFS stops cross-check), `notes.py`
    (OSM Notes), `osmose.py` (Osmose quality issues)
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
- `tests/` — pytest suite (254 passing as of last commit)
- `osm-audit-{zone}/` — generated outputs per zone (gitignored): raw Overpass
  cache under `data/`, `scan-results.json`, `reports/`, `csv/`

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
"Rider-impact findings" panel — never to the mechanical-fix queue.

- **Classifier (TIGER-fixup heuristic, mechanical-fix candidates):** Class
  A, AB, B, C; node-disconnect gaps. Defined in `classify.py` and `gaps.py`.
- **Detectors (rider-impact, human-review only):** eight detectors in
  `detectors.py` covering oneway-`-1`, parallel oneway conflicts, blocked
  residential access, unqualified barriers, broken turn restrictions,
  arterial-named residentials, missing arterial maxspeeds, misplaced bus
  stops.

Mechanical fixes from CAGIS conflation supplement the classifier track only,
not the detector track.
