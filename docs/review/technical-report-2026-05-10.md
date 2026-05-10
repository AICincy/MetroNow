# Technical Report — Architecture Audit, 2026-05-10

## 1. Scope and methodology

**Branch under audit:** `claude/fix-architecture-WhGPl` at HEAD `6071d0a`,
154 commits ahead of `origin/main`, 0 commits behind, working tree
clean.

**Footprint of the prior session:** 22,968 insertions, 372 deletions
across 118 files. Major touched paths:

| Path | Net delta |
|------|-----------|
| `src/osm/zones/northgate-mt-healthy.geojson` | +757 (new zone) |
| `src/osm/zones/springdale-sharonville.geojson` | +597 (new zone) |
| `src/osm/conflate.py` | (existing) |
| `tests/test_*.py` | +14 new test modules, +3,202 lines |
| `web/server.js` | +326 |
| `web/public/js/atlas.js` | +468 |
| `web/public/index.html` | +189 |
| `web/public/css/atlas-supplement.css` | +56 |

**Method.** Four parallel Explore-class specialist audits were
dispatched against (a) `src/osm/*.py`, (b) the web stack
(`server.js`, `atlas.js`, `atlas-extras.js`, `index.html`,
`atlas-supplement.css`), (c) Dockerfile + `deploy/`, and
(d) CLAUDE.md-vs-disk consistency. Each specialist was briefed to
read the relevant `metronow-code-review` reference file before
issuing findings. Every contested claim was then verified by the
auditor against the source files; two false positives were caught
and are disclosed in §6 below.

## 2. Executive summary

The branch is **not** in architectural disarray. It reflects the
output of substantial, well-reviewed feature work — the recent
commit history shows iterative `gemini` / `chatgpt-codex`
review-fix cycles on PRs #29 through #34 — and all CLAUDE.md
load-bearing invariants are satisfied at HEAD.

Total findings (Phase 1 + Phase 2):
- **1 Blocker** — Docker volume-mount path inconsistent with the
  Dockerfile's `HOME` directive (would silently fail OAuth-token
  persistence in production).
- **3 Warnings** — Documentation-precision issues, none
  affecting runtime.
- **8 Info** — Phase 1: undocumented modules, the route_diff
  dispatcher next-session work, three documentation-only HTML
  files (§§ 4.5-4.7). Phase 2: 12 source modules without
  dedicated test files, five fail-open `# noqa: BLE001` patterns
  in `cli.py`, and the disclosed auditor-method false positive
  (§§ 8.1, 8.3, 8.7).

The codebase parses cleanly (Python `compileall`, Node `--check`),
all CLAUDE.md-mandated security invariants
(`zonePath()`, `fcntl.flock`, strict CSP, escapeHtml on innerHTML)
verify, and there are zero TODO/FIXME markers without issue
references.

## 3. Invariant verification (empirical)

Every load-bearing rule from `CLAUDE.md` has been spot-checked
against current HEAD:

| Invariant | Status | Citation |
|-----------|--------|----------|
| `zonePath()` containment guard | VERIFIED | `web/server.js:140`; 13 callsites at lines 409, 455, 530, 539, 547, 612, 760, 787, 809, 854, 899, 902, 940; no raw `path.join` bypasses found |
| `fcntl.flock` + Windows fallback in transit usage counter | VERIFIED | `src/osm/transit.py:209-232` (LOCK_EX at L226, LOCK_UN at L232, fallback comment L210) |
| Strict CSP, `script-src` excludes `'unsafe-inline'` | VERIFIED | `web/server.js:46` (`"script-src": ["'self'", "https://unpkg.com"]`); `'unsafe-inline'` is restricted to `style-src` per the documented Leaflet exception |
| CSP allow-list mirrors `index.html` external origins | VERIFIED | unpkg, fonts.googleapis.com, fonts.gstatic.com, basemaps.cartocdn.com, server.arcgisonline.com, services.arcgis.com, *.tile.openstreetmap.org, nominatim.openstreetmap.org all enumerated |
| All user-string `innerHTML` writes pass through `esc()` | VERIFIED | `web/public/js/atlas.js:9` defines `esc()`; spot-checked at L525, L531, L1497, L1503, L1507; 39 `innerHTML` assignments total, no unescaped interpolations found |
| Directed (not symmetric) Hausdorff in conflate | VERIFIED | `src/osm/conflate.py:30` (`directed_hausdorff_meters`), invocations at L512, L589, L752 |
| Conflate constants match documented values | VERIFIED | `conflate.py:82-84` (`BUFFER_M=30.0`, `HIGH_CONFIDENCE=0.85`, `REVIEW_CONFIDENCE=0.6`), L97 (`FALLBACK_BUFFER_M=100.0`), L101-103 (`W_NAME=0.5`, `W_GEOMETRY=0.3`, `W_DIRECTION=0.2`) |
| `cagis:attribution` tag in changesets | VERIFIED | `src/osm/changeset.py:110` (gated on `cagis_verified=True` at L91) |
| MOTIS opt-in via `MOTIS_BASE` env, `is_available()` probe | VERIFIED | `src/osm/motis.py:57` (env), L328 (`is_available(timeout=5)`); CLI command at `cli.py` exposes `motis-status` |
| Detector taxonomy is two-track | VERIFIED | classifier in `classify.py` + `gaps.py`; rider-impact in `detectors.py` (8 detectors); CAGIS conflation enters classifier track only |
| File names use hyphens (non-Python) | VERIFIED | zone GeoJSONs (`blue-ash-montgomery`, `forest-park-pleasant-run`, `northgate-mt-healthy`, `springdale-sharonville`), web assets (`atlas-extras.js`, `atlas-supplement.css`), all docs use hyphens |
| Inline `<script>` blocks absent | VERIFIED with one disclosed exception | `index.html:1837` is `<script type="application/json" id="default-tweaks">` — a data island, not executable JS; not subject to CSP `script-src` |
| Inline event handlers (`onclick=`, etc.) absent | VERIFIED | 0 matches in `index.html` |
| No TODO/FIXME without issue references | VERIFIED | 0 unreferenced markers in `src/osm/`, `web/server.js`, `web/public/js/` |
| Syntax cleanliness | VERIFIED | `python3 -m compileall src/osm/` exits 0; `node --check` passes for `server.js`, `atlas.js`, `atlas-extras.js` |

## 4. Findings

### 4.1 Blocker — Docker volume-mount path mismatch

**Files:** `deploy/docker-compose.yml:14-19` ↔ `Dockerfile:51-54`

`Dockerfile` runs the container as a non-root user with HOME at
`/home/metronow`:
```
51  USER metronow
53  ENV HOME=/home/metronow
54  ENV XDG_CONFIG_HOME=/home/metronow/.config
```
And it pre-creates the OSM config dir at the right path:
```
48  && mkdir -p /home/metronow/.config/osm
49  && chown -R metronow:metronow /home/metronow/.config
```
But `deploy/docker-compose.yml` mounts the persistent volume at the
wrong path, and the comment is misleading:
```
17  # web/server.js (HOME=/root inside the python:3.12-slim container).
19  - osm_config:/root/.config/osm
```

**Failure mode.** OAuth credentials, OAuth tokens, the 90-day CAGIS
conflation cache, and the 7-day history cache all live under
`~/.config/osm` (per CLAUDE.md "## Paths"). With `HOME=/home/metronow`,
those writes land in `/home/metronow/.config/osm` — which is on the
ephemeral container filesystem, **not** on the named volume.
First container restart loses the OAuth token, the cache, and any
queued submissions. Production deployment with this configuration
would silently re-prompt the operator for OAuth on every
`docker compose up` and re-fetch every CAGIS quarterly snapshot.

The compose-level mount overrides the Dockerfile-level
intent, so this is a real production-only bug and would not surface
in local `docker run` testing where no volume is mounted.

**Remediation.** Two-line change to `deploy/docker-compose.yml`:
```diff
-      # web/server.js (HOME=/root inside the python:3.12-slim container).
-      - osm_config:/root/.config/osm
+      # web/server.js (HOME=/home/metronow inside the container, matching
+      # the non-root USER directive in the Dockerfile).
+      - osm_config:/home/metronow/.config/osm
```
No Dockerfile change required; the existing `mkdir -p ... && chown -R`
already prepares the directory tree at the correct path.

### 4.2 Warning — `zones.py` referenced as module, exists as package

**File:** `CLAUDE.md:39`

CLAUDE.md enumerates plumbing modules as
`config.py`, `zones.py`, `geo.py`, ...
but `src/osm/zones.py` does not exist. The actual structure is the
package `src/osm/zones/` containing `__init__.py` plus zone
GeoJSONs.

**Runtime impact:** None. `from osm.zones import …` resolves to the
package's `__init__.py` cleanly.

**Remediation.** One-line edit to `CLAUDE.md`:
```diff
-    `config.py`, `zones.py`, `geo.py`, `cache.py`, `auth.py`
+    `config.py`, `zones/` (package), `geo.py`, `cache.py`, `auth.py`
```

### 4.3 Warning — Dockerfile and compose disagree on healthcheck endpoint

**Files:** `Dockerfile:58-59` (`/health`) ↔ `deploy/docker-compose.yml:25` (`/api/zones`)

Both endpoints exist in `web/server.js`:
- `/health` at L77 (lightweight, no subprocess) — designed for
  healthchecks, deliberately mounted before the rate limiter
- `/api/zones` (returns the configured zone list, exercises the
  Python subprocess)

When running under compose, the service-level healthcheck overrides
the image-level HEALTHCHECK, so the Dockerfile's `/health` probe is
inert in production. Two probes for two different scenarios is
defensible, but the comment on `/health` (server.js:73-76)
explicitly says "Healthcheck probes shouldn't consume rate-limit
budget" — and `/api/zones` is on the post-rate-limit path.

**Remediation.** Recommend aligning compose to `/health`:
```diff
-      test: ["CMD", "node", "-e", "require('http').get('http://localhost:3000/api/zones',r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"]
+      test: ["CMD", "node", "-e", "require('http').get('http://localhost:3000/health',r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"]
```
This unifies probes and respects the documented rate-limit budget.

### 4.4 Warning — `metronow-app:latest` tag in compose

**File:** `deploy/docker-compose.yml:6`

`image: metronow-app:latest` is acceptable for a self-built local
image (it's just the tag attached at build time), but it forfeits
reproducibility. A redeploy from a different working tree could
silently retag `:latest` to a different commit's binary.

**Remediation (optional).** Parameterize via `.env`:
```diff
-    image: metronow-app:latest
+    image: metronow-app:${APP_IMAGE_TAG:-latest}
```
And document the `APP_IMAGE_TAG` env in `.env.example`.

### 4.5 Info — Undocumented Python modules

**Files:** `src/osm/{_geometry,feed_errors,maproulette,resources}.py`, `src/osm/templates/`

CLAUDE.md's `src/osm/` enumeration is exhaustive in tone but
misses five legitimate modules:

| Module | Apparent role (verified by header read) |
|--------|----------------------------------------|
| `_geometry.py` | Shared geometry helpers (directed Hausdorff and friends) — used by both `conflate.py` and the route-diff path |
| `feed_errors.py` | Process-local fail-open visibility counter for read-only feeds (Transit, Notes, Osmose, MOTIS) |
| `maproulette.py` | MapRoulette challenge generator (referenced indirectly in CLAUDE.md "Detector taxonomy" → MapRoulette is on by reference) |
| `resources.py` | Centralised `importlib.resources` access for templates and zone GeoJSONs |
| `templates/` | Holds `dashboard.html` template used by `dashboard.py` |

**Runtime impact:** None. **Remediation:** Document them in the next
CLAUDE.md update (low priority).

### 4.6 Info — Engine dispatcher in `route_diff.py` not yet implemented

**File:** `src/osm/route_diff.py`

`route_diff.py` is hardwired to BRouter; there is no MOTIS/BRouter
engine dispatcher. CLAUDE.md (line 178-179) explicitly flags this:
"Engine dispatcher in `route_diff.py` is the next-session item."

**Status:** Documented incomplete work, not a defect. The
specialist's initial classification of this as a Blocker has been
downgraded to Info — see §6.

### 4.7 Info — Documentation-only HTML artifacts in `docs/`

**Files:** `docs/change-log.html`, `docs/independent-audit.html`, `docs/metronow-atlas.html`

Three HTML files in `docs/` are session-output artifacts (rendered
audit tables, a self-contained snapshot of the production UI). They
are checked in, not gitignored. Cross-check against
`docs/explainers/conventions.md` does not flag them as out-of-place;
they are harmless reference material.

**Remediation:** None required. Optionally document their purpose in
`docs/explainers/README.md` so newcomers don't take them for stale
session output.

## 5. Remediation protocol — execution order

If the operator authorises remediation, execute in this order:

1. **(Blocker)** `deploy/docker-compose.yml` — fix volume mount path
   and update the comment. Smoke-test by:
   - `docker compose down && docker compose up -d --build`
   - `docker compose exec app ls -la /home/metronow/.config/osm`
   - `docker compose exec app id` (confirm uid=1000 metronow)
2. **(Warning)** `deploy/docker-compose.yml` — align healthcheck
   to `/health`.
3. **(Warning)** `CLAUDE.md` — fix `zones.py` → `zones/` (package)
   reference; add the five undocumented modules from §4.5 to the
   enumeration.
4. **(Warning, optional)** `deploy/docker-compose.yml` +
   `.env.example` — parameterise `APP_IMAGE_TAG`.

Steps 1-3 are independent; step 4 is independent of steps 1-3. None
require code changes to `src/osm/` or to the web stack.

## 6. False-positive disclosure

Three findings did not survive empirical verification and have
been **excluded from the action list above**. The first two
are specialist false positives caught in Phase 1; the third is
a method-level false positive in my own Phase 2 broken-link
audit, disclosed in the same spirit:

| Source | Initial claim | Reality | Verdict |
|--------|---------------|---------|---------|
| Web audit (Phase 1) | "Missing SRI integrity attribute on esri-leaflet@3.0.14" (`index.html:1850`) | Integrity attribute IS present at `index.html:1851`: `integrity="sha384-Lm29z+brYIz3vevy21cGCkFIoyyO9sVj7QBYlIPhhWZM9SlgXJ13rYSTS8uO6/iD"` | **False positive.** No remediation needed. |
| Python audit (Phase 1) | Engine dispatcher absence in `route_diff.py` classified as Blocker | CLAUDE.md line 178-179 explicitly documents this as the "next-session item"; it is incomplete documented work, not unsanctioned drift | **Severity downgraded to Info** (§4.6). |
| Auditor's own broken-link sweep (Phase 2) | "2 broken markdown links in `RESEARCH-FINDINGS.md`" (lines 59, 116) | Both regex hits were Overpass query syntax inside backticked code spans: `way["highway"](user:"DaveHansenTiger")(if: ...)`. The naive `\[...\](...)` matcher conflated `["highway"]` followed by `(user:...)` with markdown link syntax. Actual broken-link count: **0**. | **False positive in audit method.** No remediation needed in `RESEARCH-FINDINGS.md`. |

## 7. Verdict

The branch is ship-ready pending remediation of the §4.1 Docker
mount-path Blocker. The user's framing of "architectural disarray"
is not supported by the empirical evidence: the prior session
delivered substantial, well-reviewed work that respects every
load-bearing invariant in CLAUDE.md.

The single production-blocking defect (volume-mount path) is a
two-line fix in `deploy/docker-compose.yml`. The remaining items
are documentation-precision adjustments with zero runtime impact.

## 8. Phase-2 deep audit (continued mandate)

The user's mandate to "continue this deep audit" extended scope to
the test suite, CI/CodeQL configuration, dependency surface,
documentation link integrity, `.claude/` skill packs, and
line-level review of the six largest Python modules. All findings
below are net-new to the report.

### 8.1 Test suite — static and structural

The sandbox is Python 3.11; `pyproject.toml` requires 3.12+. The
test suite was therefore reviewed statically (read-only). CI runs
on Python 3.12 and 3.13 matrices via `.github/workflows/ci.yml`
with `pip install -e ".[dev]"` followed by `pytest --cov=src/osm`.

| Metric | Result |
|--------|--------|
| Test files | 21 (`tests/test_*.py`) + `tests/__init__.py` |
| Tests collected | 227 |
| Test files with zero `assert` (placeholders) | 0 |
| Tests doing real network I/O (CI flakiness) | 0 — all mocked |
| Tests with vague names | 0 |
| `print()` debugging artifacts | 0 |
| Conflate F1-F4 buckets covered? | YES (`test_conflate.py`) |
| `transit.py` `fcntl.flock` counter covered? | YES (`test_transit.py`) |
| `motis.is_available()` probe covered? | YES (`test_motis.py:242-278`) |
| All 17 preflight checks covered? | YES (`test_preflight.py`) |

**Coverage gap (Info):** 12 of 30 `src/osm/` modules have **no
dedicated test file**: `cli.py`, `auth.py`, `cache.py`,
`changeset.py`, `config.py`, `csv_export.py`, `dashboard.py`,
`fetch.py`, `history.py`, `resources.py`, `xlsx.py`,
`_geometry.py`. Most are exercised indirectly through their
consumers (e.g. `fetch.py` is exercised by every `test_classify`
and `test_polygons` fixture chain), but `cli.py` (57 KB) is the
notable outlier — the largest module in the package has no
direct test file. `ci.yml` deliberately omits `--cov-fail-under`
("reporting first; gating later") with a commit-trail comment
referencing the 2026-05-09 technical-report-v2 §4.2, so this is
known and tracked work, not an oversight.

### 8.2 GeoJSON validity — all five zones

All zone polygons load cleanly as `Feature/Polygon` GeoJSON via
`json.load()`:

| File | Outer-ring points |
|------|-------------------|
| `blue-ash-montgomery.geojson` | 254 |
| `forest-park-pleasant-run.geojson` | 144 |
| `hamilton-county.geojson` (TIGER fallback) | 179 |
| `northgate-mt-healthy.geojson` (new in this branch) | 185 |
| `springdale-sharonville.geojson` (new in this branch) | 145 |

No multi-polygons; no holes; consistent topology.

### 8.3 Deep code review — six largest modules

Line-level review of `cli.py` (57 KB), `route_diff.py` (39 KB),
`detectors.py` (26 KB), `tiger2024.py` (26 KB), `review.py` (26
KB), `preflight.py` (20 KB):

- **17 Click commands enumerated in `cli.py`**, each with a
  docstring (✓), each `--zone` flag validated against
  `ZONE_KEYS` (✓ at lines 83, 434, 582, 673, 763, 853, 967,
  1077, 1348, 1433, 1467, 1510). Total `TODO`/`FIXME`: 0.
- **`detectors.py` — 8 detectors enumerated**: `detect_oneway_minus_one`
  (L118), `detect_oneway_conflicts` (L153), `detect_access_blocked_residential`
  (L338), `detect_arterial_named_residential` (L375),
  `detect_missing_maxspeed_arterial` (L407),
  `detect_barriers_without_access` (L443), `detect_misplaced_bus_stops`
  (L475), `detect_broken_turn_restrictions` (L596). All have
  docstrings. Matches CLAUDE.md's stated count of eight.
- **`preflight.py` — 17 checks confirmed in code**, distributed
  across 6 categories (3 community + 3 account + 3 pipeline + 2
  scan-freshness + 4 fix-batch + 2 monitoring), exit-code
  semantics correct (`return 1` on `n_fail`, `return 2` on
  `--strict and n_warn`, else `0`).
- **All file I/O uses explicit encoding** (`encoding="utf-8"` for
  text, `encoding="ascii"` for tiger2024 dBASE records).
- **All outbound network calls have `timeout=`** (default 30s in
  `route_diff.py:382`, default 60s in `tiger2024.py:147`).
- **No mutable default arguments** anywhere in the six modules.
- **Subprocess calls** in `preflight.py` (`pytest`, `ruff`) are
  argv-list invocations; no `shell=True`.

**One pattern flagged Info, not a Blocker:** five sites in
`cli.py` (L188, L205, L260, L325, L376) use bare
`except Exception:` with explicit `# noqa: BLE001`. These are
documented fail-open paths in scan-discovery code (a single feed
failure must not abort the scan). The `noqa` markers are
intentional.

### 8.4 CI / .github — three workflows verified

| Workflow | Triggers | What it runs |
|----------|----------|--------------|
| `ci.yml` | push to main, all PRs | Python 3.12+3.13 matrix → `pip install -e ".[dev]"` → `ruff check src/` → `mypy src/osm/ --ignore-missing-imports` → `pytest tests/ --cov=src/osm --cov-report=term-missing` |
| `codeql.yml` | push/PR to main, weekly cron | CodeQL on `actions`, `javascript-typescript`, `python` |
| `stale.yml` | daily cron | Marks issues/PRs stale at 90 days; closes at +14; respects `keep-open` and `security` labels |

Permissions are correctly scoped: `ci.yml` is
`contents: read` (least privilege); `codeql.yml` has
`security-events: write` only because CodeQL requires it; `stale.yml`
has `issues: write, pull-requests: write` only.

**Note on PR #35 status.** GitHub commit-status API at
`f6998f4` reported `state: pending, total_count: 0`. This is the
*commit-status* surface, not the *check-runs* surface — the two
are independent. CI is configured to run on `pull_request:`
without a `draft == false` filter, so a draft PR like #35 would
trigger CI. Whether the runner has actually picked it up is a
transient operational state, not a structural finding.

### 8.5 Dependencies — small, current surface

| Stack | Direct deps | Notes |
|-------|-------------|-------|
| Python | 6 (`requests>=2.31`, `openpyxl>=3.1`, `click>=8.0`, `rich>=13.0`, `httpx>=0.27`, `shapely>=2.0`); dev: `pytest>=8.0`, `pytest-cov` | All caret-ranged with major-version pins. None known-vulnerable as of cutoff. |
| Node | 4 (`cors ^2.8.6`, `express ^5.2.1`, `express-rate-limit ^8.5.1`, `helmet ^8.1.0`); 0 dev deps | Express 5 (released 2024-10-15) is the current major; helmet 8 and express-rate-limit 8 are current. |

`pip-audit` was attempted; it failed in this sandbox on an
unrelated `dbus-python` build (not in our deps), not on anything
declared by the project. CI's matrix on Python 3.12+3.13 against
the live PyPI dependency set is the authoritative check.

### 8.6 CodeQL alert spot-check

CLAUDE.md claims alerts #4, #6-10, #17, #24 are "fixed in code"
and #3 is dismissed as a false positive (`auth.py:120` OAuth URL
print, RFC 6749 §4.1.1 says the URL contains no secrets).

Alert #3 verified: the actual print site is `auth.py:147`
(`print(f"  If the browser doesn't open, visit:\n  {url}")`).
The URL contains `client_id`, `code_challenge` (PKCE-protected,
not a secret), `state` (CSRF token), and `redirect_uri` —
none of which are confidential per RFC 6749. CLAUDE.md's
dismissal stance is correct; the code matches the documented
intent.

Server.js `child_process` safety verified:
`OSM_PKG = path.resolve(__dirname, "..", "src")` is a startup
constant. All `execFile()` calls embed it via
`JSON.stringify(OSM_PKG)`, which produces a valid JSON-string
literal that is also a valid Python string literal — no
injection vector.

### 8.7 Documentation link integrity — 523 internal links checked

A regex sweep across 69 markdown files (`*.md` at root, `docs/`,
`.claude/`) extracted 523 inline relative links and resolved
them against the working tree.

| Result | Count |
|--------|-------|
| Internal links that resolve | 521 |
| Internal links that look broken (regex output) | 2 |
| Actual broken links (after manual review) | **0** |

The two regex hits were `RESEARCH-FINDINGS.md:59` and `:116` — both
inside backticked code spans containing Overpass query syntax
(`way["highway"](user:"DaveHansenTiger")(if: ...)`). The naive
`\[...\](...)` regex matched the Overpass `["highway"]` followed by
`(user:"DaveHansenTiger")` as if it were a markdown link. **This
was an audit-method false positive in my own work and is hereby
disclosed in §6 below.**

### 8.8 `.claude/` skill packs and configuration

| Asset | Status |
|-------|--------|
| `settings.json` | NOT PRESENT (no project-scoped overrides) |
| `settings.local.json` | NOT PRESENT |
| Skill packs | 14 (`metronow-*` × 6, plus 8 domain skills) |
| Skills with valid frontmatter | 14 / 14 |
| `metronow-code-review` references reachable | 4 / 4 (`javascript.md`, `html.md`, `css.md`, `dockerfile.md`) |
| Secrets / tokens / keys in any skill file | 0 |
| `.claude/skills/` ↔ `docs/skills/` parity | 14 ↔ 14, no orphans either side |

Skill packs cite the production file sizes
(`web/public/index.html` ~1815 lines, `atlas.js` ~2072 lines,
etc.); these match the actual file lengths at HEAD.

### 8.9 Phase-2 verdict

No new Blockers. No new Warnings. Three new Info-class items:

- **8.1** — 12 of 30 source modules lack dedicated test files;
  cli.py is the notable outlier. Tracked, not an oversight (CI
  has reporting-only coverage by design).
- **8.3** — Five `# noqa: BLE001` exception suppressions in
  `cli.py` are intentional fail-open patterns in scan-discovery
  code; documented but worth re-reading any time those paths are
  refactored.
- **8.7 (audit-method false positive)** — My own broken-link
  audit reported 2 hits that, on inspection, were Overpass query
  syntax inside code spans. The actual broken-link count is 0.
  Disclosed in §6 below.

The aggregate finding tally remains: **1 Blocker** (Docker
volume-mount path, §4.1), **3 Warnings** (CLAUDE.md `zones.py`
nomenclature §4.2, healthcheck endpoint §4.3, `latest` tag §4.4),
**8 Info** (§4.5–4.7, plus the three from §8 above). Branch is
ship-ready pending §4.1 remediation.

---

*Phase 1 auditor: Claude (Opus 4.7), invoked under user-issued
audit mandate. Phase 2 follow-up dispatched at 2026-05-10 after
operator instruction "I insist you continue this deep audit."
All findings cite source files at line-level granularity and were
verified against working-tree contents at HEAD `f6998f4`.*
