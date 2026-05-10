# Tests overview — what's tested, what isn't, how to run

**Summary.** The test suite at `tests/` is a comprehensive pytest collection across
**22 files**, one per `src/osm/` module. Pure pytest — no fixtures
directory, no conftest.py, just hand-built minimal element dicts and
inline assertions. Tests are deterministic by default; the few that
hit the network (history fetches, real CAGIS server) are either
mocked or skipped when offline. CI runs them on Python 3.12 and 3.13
in parallel.

---

## What's here

The `tests/` directory layout mirrors `src/osm/` — one test file per
module, named `test_<module>.py`. Test data is constructed inline via
small helper functions like `_make_way()` and `_overpass_response()`
that return minimal Overpass-shaped dicts with just the fields the
module under test needs. No fixtures directory. No mock objects unless
mocking a network call.

| Module under test | Test file | Concern |
|---|---|---|
| `osm.classify` | `test_classify.py` | Class A/AB/B/C bucketing |
| `osm.detectors` | `test_detectors.py` | Eight rider-impact detectors |
| `osm.gaps` | `test_gaps.py` | Haversine endpoint disconnect |
| `osm.geo` | `test_geo.py` | Distance / direction helpers |
| `osm.conflate` | `test_conflate.py`, `test_conflate_pagination.py` | Matcher core + paged CAGIS load |
| `osm.review` | `test_review.py` | Three-layer fix-proposal stack |
| `osm.history_filter` | `test_history_filter.py` | Two-tier review-status |
| `osm.polygons` | `test_polygons.py` | Centroid containment clip |
| `osm.preflight` | `test_preflight.py` | The 17 codified checks |
| `osm.maproulette` | `test_maproulette.py` | Class A/AB filter + GeoJSON serialize |
| `osm.route_diff` | `test_route_diff.py` | BRouter perturbation logic |
| `osm.motis` | `test_motis.py` | MOTIS client (degrade-to-None) |
| `osm.gtfs` | `test_gtfs.py` | SORTA GTFS feed loader |
| `osm.bus_routes` | `test_bus_routes.py` | CAGIS METRO Bus Routes |
| `osm.notes` | `test_notes.py` | OSM Notes API client |
| `osm.osmose` | `test_osmose.py` | Osmose quality issues |
| `osm.transit` | `test_transit.py` | Transit App quota + cache |
| `osm.tiger2024` | `test_tiger2024.py` | TIGER 2024 fallback |
| `osm.feed_errors` | `test_feed_errors.py` | External-feed error envelope |
| CLI transit subcommands | `test_cli_transit.py` | `osm transit-status / -budget` |

## How tests stay fast

- **Inline test data, not fixtures on disk.** Every test that needs a
  way builds one with `_make_way()`. The pattern is small enough that
  test data lives next to the assertion — no jumping between fixture
  files and test logic.
- **No real Overpass calls.** The classifier, detectors, and gap
  modules accept dict inputs, so tests pass synthetic responses
  without touching the network.
- **Mocked HTTP for CAGIS / OSM API / Transit App / BRouter / MOTIS.**
  Each external client has a test that mocks `requests.get`/`post`
  and verifies request shape + response handling.
- **Cache layers are exercised via tmp paths.** Tests using
  `osm.transit` etc. point cache dirs at `tmp_path` so concurrent test
  runs don't collide.

## What's deliberately NOT tested

- **Web frontend (`web/public/js/*.js`).** Vanilla JS with no test
  framework. Audits via `metronow-javascript-review` skill, not pytest.
- **Express server (`web/server.js`).** Same — covered by Node lint
  in CI, but no JS unit tests beyond that. Behavioral changes are
  caught by manual smoke against `node web/server.js` + the dashboard.
- **Real OSM Notes / CAGIS / Transit-App network calls.** Mocked at
  the `requests` boundary. Real calls would need credentials and
  quota; CI has neither.
- **Generated reports (XLSX / dashboard / CSVs).** Output structure is
  tested; rendered visual fidelity is checked by hand.
- **The audit pipeline end-to-end.** Each stage is tested in
  isolation; the integration is verified via `osm preflight --zone
  blue-ash-montgomery` runs, not pytest.

## How to run

```bash
# Full suite
pytest tests/ -v

# One module
pytest tests/test_classify.py -v

# With coverage (matches CI)
pytest tests/ --cov=src/osm --cov-report=term-missing

# Skip the slow ones (history-fetch tests)
pytest tests/ -v -m "not slow"
```

CI runs the suite on Python 3.12 and 3.13 with coverage, uploads the
result as `python-coverage-<version>` artifacts, and additionally
verifies the wheel bundles all data files (zone GeoJSONs, templates).
See `.github/workflows/ci.yml`.

## Patterns to follow when adding a test

1. **One file per module.** `tests/test_<module>.py`; mirror the source
   tree.
2. **Inline test data via small helpers.** Mimic `_make_way()` /
   `_overpass_response()` — tiny dicts that look like Overpass output.
3. **Use `tmp_path` for any disk I/O.** Cache dirs, output dirs,
   manifest files all point at pytest's `tmp_path` fixture.
4. **Mock at the `requests` boundary.** Use `monkeypatch` to swap in a
   stub `requests.get`/`post` rather than actually hitting external
   services.
5. **No new dependencies.** The test suite uses pytest + the project's
   own dependencies. Adding fixture libraries, mocking frameworks, or
   property-based testing tools needs explicit discussion.

## Code references

- [`tests/__init__.py`](../tests/__init__.py) — empty marker; exists
  so `pytest` can import `tests.*` without warnings.
- [`tests/test_classify.py`](../tests/test_classify.py) — reference
  example of the inline-data + helper pattern.
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — CI
  configuration; pytest invocation + coverage flags.

## See also

- [`CLAUDE.md` § Layout / `tests/`](../CLAUDE.md) — "pytest suite overview."
- [`docs/explainers/preflight-checks.md`](explainers/preflight-checks.md)
  — `check_pytest_passes` is one of the 17 codified pre-flight checks.
- [`docs/skills/metronow-code-review.md`](skills/metronow-code-review.md)
  — code-review skill that complements the test suite for the
  non-pytest-tested surfaces (HTML / CSS / JS / Dockerfile).
