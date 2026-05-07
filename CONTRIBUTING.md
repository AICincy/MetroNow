# Contributing

## Setup

Prerequisites:

- Python 3.12+
- Node.js 20+

Install the Python package in editable mode with dev dependencies:

```
pip install -e ".[dev]"
```

Install the web frontend dependencies:

```
cd web && npm install
```

## Credential setup

To submit corrections to OpenStreetMap, you need OAuth 2.0 credentials.

1. Log in to [openstreetmap.org](https://www.openstreetmap.org)
2. Go to [My Settings > OAuth 2 applications](https://www.openstreetmap.org/oauth2/applications)
3. Register a new application:
   - Redirect URI: `urn:ietf:wg:oauth:2.0:oob`
   - Scopes: `write_api`, `read_prefs`
4. Create the credentials file at `~/.config/osm/credentials.json`:

```json
{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET"
}
```

See `.env.example` for optional environment variable overrides.

## Running

Run an audit scan for a specific zone:

```
osm scan --zone blue-ash-montgomery --skip-history
```

Start the web dashboard:

```
cd web && npm start
```

Then open `http://localhost:3000` in your browser.

## Testing

Run the test suite:

```
pytest tests/ -v
```

Run the linter:

```
ruff check src/
```

## Project structure

```
src/osm/              Python package (core logic)
  cli.py               CLI entry point (click)
  fetch.py             Overpass API queries
  classify.py          Defect classification (A/B/AB/C)
  gaps.py              Node disconnect / gap detection
  geo.py               Haversine and geometry utilities
  history.py           OSM revision history analysis
  history_filter.py    TIGER import timestamp filtering
  changeset.py         OSM API v0.6 changeset submission
  auth.py              OAuth 2.0 authentication
  config.py            Configuration and defaults
  zones.py             MetroNow service zone definitions
  cache.py             Response caching
  review.py            Review workflow logic
  csv_export.py        CSV export
  xlsx.py              XLSX workbook generation
  dashboard.py         Leaflet dashboard generation
web/                   Express.js API + vanilla HTML/CSS/JS frontend
  server.js            Bridges web UI to the Python backend
  public/              Static frontend assets
tests/                 pytest test suite
  test_classify.py     Classification logic tests
  test_geo.py          Geometry utility tests
```

## PR conventions

- Use hyphens in branch names (e.g., `fix-oneway-detection`, not `fix_oneway_detection`)
- Write concise commit messages that describe the "why," not just the "what"
- Run `pytest tests/ -v` and `ruff check src/` before submitting
- Keep PRs focused on a single change when possible

## OSM community compliance

All automated edits to OpenStreetMap must comply with the
[Automated Edits code of conduct](https://wiki.openstreetmap.org/wiki/Automated_Edits_code_of_conduct).

Key requirements:

- All corrections must be reviewable and documented
- Changeset comments must clearly describe what was changed and why
- Edits must be traceable back to this tool and its audit methodology
- Community discussion should precede bulk edits to a new area
