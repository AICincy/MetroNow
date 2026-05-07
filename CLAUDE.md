# MetroNow

OSM road defect detection and correction for Hamilton County MetroNow microtransit zones. Via Transportation's ViaMapping routing layer is built on OpenStreetMap — fixes here improve MetroNow service.

## Layout

- `src/osm/` — Python package (pip-installable as `osm`)
- `web/` — Express.js server + vanilla HTML/CSS/JS frontend
- `web/server.js` — API on port 3000, calls Python via child_process
- `web/public/` — Static frontend (index.html, css/style.css, js/app.js)

## Paths

- Python: `C:\Users\krass\AppData\Local\Python\pythoncore-3.14-64\python.exe`
- Node: `C:\Program Files\nodejs\node.exe`
- Web server: `node web/server.js` (localhost:3000)
- OAuth: OOB redirect (`urn:ietf:wg:oauth:2.0:oob`), credentials at `~/.config/osm/credentials.json`

## Conventions

- File names use hyphens, never underscores
- No CLI instructions to the user — run everything directly
- Auto mode is the default — make decisions, don't present menus
- Audit work before declaring done — run seam-level checks, no false-confident sign-offs

## OSM community requirements

- Mechanical edits require wiki documentation, `talk-us@` discussion, and `_cincyimport`-convention account
- Changeset community norm is ~500 elements (CGImap hard limit 10,000)
- Use MapRoulette for corrections with >5% expected false-positive rate
- Ground truth: CAGIS quarterly centerlines, ODOT TIMS, TIGER/Line 2024
