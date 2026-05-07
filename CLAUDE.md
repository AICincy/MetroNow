# OSM TIGER Audit Pipeline

Python backend + Express.js web UI for auditing and correcting TIGER/Line import defects in Hamilton County, OH.

## Project layout

- `src/osm/` — Python package (pip-installable as `osm`)
- `web/` — Express.js server + vanilla HTML/CSS/JS frontend
- `web/server.js` — API server on port 3000, calls Python via child_process
- `web/public/` — Static frontend (index.html, css/style.css, js/app.js)

## Running

- Python: `C:\Users\krass\AppData\Local\Python\pythoncore-3.14-64\python.exe`
- Node: `C:\Program Files\nodejs\node.exe`
- Web server: `node web/server.js` (serves on localhost:3000)
- OAuth: OOB redirect (`urn:ietf:wg:oauth:2.0:oob`), credentials at `~/.config/osm/credentials.json`

## Conventions

- File names use hyphens, never underscores
- No CLI instructions to the user — run everything directly
- Auto mode is the default — make decisions, don't present menus
