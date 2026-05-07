# MetroNow

Improving on-demand transit routing in Hamilton County, OH by detecting and correcting OpenStreetMap road defects in SORTA's MetroNow microtransit service zones.

## Why this matters

[MetroNow](https://www.go-metro.com/metronow) is Hamilton County's on-demand microtransit service, operated by [Via Transportation](https://ridewithvia.com/) for SORTA (Southwest Ohio Regional Transit Authority). Via's routing engine — ViaAlgo — builds its road network from OpenStreetMap through a custom layer called ViaMapping.

In 2007-2008, the U.S. Census Bureau's TIGER/Line road data was bulk-imported into OpenStreetMap. Many segments in the northern suburban arc of Hamilton County — where MetroNow operates — were never reviewed. These import artifacts include false one-way tags on residential streets, disconnected road segments, and incorrect highway classifications. They cause real routing failures: missed pickups, circuitous detours, and service denials.

Fixing OSM in the MetroNow zones feeds directly into Via's routing tiles, improving service for riders.

## How it works

1. **Scan** — Queries Overpass API for road segments untouched since the 2007 TIGER import, using the `DaveHansenTiger` user+timestamp filter
2. **Classify** — Ranks defects by severity and detects node disconnects via haversine endpoint analysis
3. **Report** — Generates XLSX workbooks, interactive Leaflet dashboards, and CSV exports
4. **Correct** — Submits fixes to OpenStreetMap via API v0.6 changesets (OAuth 2.0)

## Defect classes

| Class | Description | Risk |
|-------|-------------|------|
| **AB** | False oneway + multi-segment (compound) | Highest |
| **A** | False `oneway=yes` on residential streets | High |
| **B** | Multi-segment streets with disconnect risk | Moderate |
| **C** | Unreviewed, no immediate signal | Low |

## Service zones

| Zone | Coverage |
|------|----------|
| Blue Ash / Montgomery | Blue Ash, Montgomery, Deer Park, Silverton, Kenwood, Madeira |
| Springdale / Sharonville | Springdale, Sharonville, Glendale, Evendale, Lincoln Heights |
| Northgate / Mt. Healthy | Mt. Healthy, North College Hill, Finneytown, Northgate |
| Forest Park / Pleasant Run | Forest Park, Pleasant Run, Greenhills |

## Getting started

Requires Python 3.12+ and Node.js 20+.

```
pip install -e .
cd web && npm install && npm start
```

Open `http://localhost:3000` in your browser.

- **Scan** — Pick a zone and run an audit
- **Results** — Browse defect tables with direct links to OpenStreetMap
- **Authenticate** — Connect your OSM account to submit corrections

## Architecture

```
src/osm/          Python package — Overpass queries, classification,
                   gap detection, history analysis, changeset submission
web/               Express.js API + vanilla HTML/CSS/JS frontend
web/server.js      Bridges the web UI to the Python backend
```

## Background

Successor to [AICincy/Tiger](https://github.com/AICincy/Tiger). Key improvement per OSM community feedback from [Minh Nguyen](https://wiki.openstreetmap.org/wiki/User:Mxn): the `tiger:reviewed=no` tag is unreliable because most mappers don't remove it after correcting data. The current pipeline still uses `tiger:reviewed=no` to fetch initial candidate road segments from Overpass, then supplements that baseline with revision history analysis and the `DaveHansenTiger` import-timestamp filter to better identify likely TIGER import artifacts.

See [RESEARCH-FINDINGS.md](RESEARCH-FINDINGS.md) for the full technical investigation into Via's data architecture, TIGER defect taxonomy, and OSM community integration requirements.

## License

[MIT](LICENSE)
