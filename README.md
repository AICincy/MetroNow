# MetroNow — TIGER Audit & Correction Pipeline

Detects and corrects unreviewed TIGER/Line Census import defects in OpenStreetMap road data across Hamilton County, OH MetroNow microtransit service zones.

Successor to [AICincy/Tiger](https://github.com/AICincy/Tiger).

## What it does

The 2007-2008 TIGER/Line Census import added road geometry to OpenStreetMap across the United States. Many segments in Hamilton County were never reviewed, leaving behind defects that cause routing failures in Via Transportation's MetroNow microtransit service.

This pipeline:

1. **Scans** — Queries Overpass API for unreviewed road segments with full metadata
2. **Analyzes** — Classifies defects by severity (Class AB, A, B, C) and detects node disconnects
3. **Reports** — Generates XLSX workbooks, Leaflet dashboards, and CSV exports
4. **Corrects** — Submits fixes to OpenStreetMap via API v0.6 changesets (OAuth 2.0)

## Defect classes

| Class | Description | Risk |
|-------|-------------|------|
| **AB** | False oneway + multi-segment (compound) | Highest |
| **A** | False `oneway=yes` on residential streets | High |
| **B** | Multi-segment streets with disconnect risk | Moderate |
| **C** | Unreviewed, no immediate signal | Low |

## Service zones

- Blue Ash / Montgomery
- Springdale / Sharonville
- Northgate / Mt. Healthy
- Forest Park / Pleasant Run

## Setup

Requires Python 3.12+ and Node.js 20+.

```
pip install -e .
cd web && npm install
```

## Usage

Open the web UI at `http://localhost:3000` after starting the server:

```
cd web && npm start
```

- **Scan tab** — Select a zone and run an audit
- **Results tab** — View defect tables with links to OSM
- **Authenticate tab** — Connect to OpenStreetMap for submitting corrections

## Architecture

- `src/osm/` — Python package handling Overpass queries, defect classification, gap detection, history analysis, changeset submission
- `web/` — Express.js server + vanilla HTML/CSS/JS frontend
- OAuth 2.0 with OOB redirect for authentication

## Key improvement over Tiger

Per feedback from OSM community member Minh Nguyen: the `tiger:reviewed=no` tag is unreliable because most mappers don't remove it after correcting data. This pipeline optionally analyzes revision history via the OSM API to determine whether ways have actually been reviewed, producing a higher-confidence defect set.

## License

MIT
