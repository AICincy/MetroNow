# Triage Review: MetroNow Technical Report (2026-05-09)

## Summary

The report audits frontend, Python packaging, API, caching, conflation, and
testing. Verified against the tree at `9836bb9`, **12 of 18 recommendations
stand as written, 3 are rejected on false premises, and 3 need rewriting
because the underlying defect is real but the cited evidence is wrong**.
Sections 1, 3, 4, and 6 are largely accurate. Section 2 (Python packaging)
is mostly false: it claims missing files that already exist. Section 5
overstates one defect.

This review is a triage record — no code changes here. A follow-up PR can
cherry-pick the accepted items.

## Methodology

Each claim was verified by reading the cited file at `9836bb9` and
recording line numbers. Claims that depend on absent files were verified
with `ls` / `find`. Test counts were taken from
`grep -rE "^[[:space:]]*def test_" tests/`.

## Triage Table

| ID    | Recommendation                              | Verdict   | Evidence                                                                                       |
|-------|---------------------------------------------|-----------|-------------------------------------------------------------------------------------------------|
| R1.1  | Extract panel modules from `atlas.js`       | ACCEPT    | `web/public/js/atlas.js` is 2,070 lines, IIFE-wrapped, no `import`/`export`, no classes.        |
| R1.2  | Pub/sub event bus                           | ACCEPT    | Cross-panel coupling lives on `window.atlasRedraw` / `window.atlasState` (atlas.js:2062–2063). |
| R1.3  | Add `esbuild` build pipeline                | ACCEPT    | `web/package.json` has only `start` and `dev` scripts; no bundler in deps.                     |
| R2.1  | Add `pyproject.toml`                        | REJECT    | `pyproject.toml` already exists at repo root (548 bytes, setuptools build).                    |
| R2.2  | Cross-platform `fcntl` abstraction          | REJECT    | `src/osm/transit.py:215` already does `try: import fcntl` with a Windows-safe fallback path.   |
| R2.3  | CI matrix: Win/mac × Py 3.9/3.11/3.12       | REWRITE   | `.github/workflows/ci.yml:17,20` runs Linux-only with Py 3.12/3.13. Expand OS, drop 3.9.       |
| R3.1  | Staged timeout warnings                     | ACCEPT    | `web/server.js:140` hardcodes `timeout: 300000`; no progress signal.                           |
| R3.2  | SSE for scan progress                       | ACCEPT    | No `event-stream` / SSE endpoint in `web/server.js`; `/api/scan` is fully synchronous.         |
| R3.3  | Structured error responses                  | ACCEPT    | `safeError()` at `web/server.js:128–133` returns a single trimmed string with no error code.   |
| R4.1  | `/api/cache/status` + purge endpoints       | ACCEPT    | `grep "api/cache" web/server.js` returns nothing.                                              |
| R4.2  | Invalidate scan cache on submit             | ACCEPT    | No invalidation wiring exists in the `/api/fix` handler.                                       |
| R4.3  | Cache versioning (content hash)             | ACCEPT    | Sound; lower priority than R4.1.                                                               |
| R5.1  | Surface shapely-missing as a UI warning     | ACCEPT    | `conflate.py:166` logs a warning, but `web/server.js:283` silently skips on `SHAPELY_AVAILABLE=False`; the warning never reaches the UI. |
| R5.2  | Document conflation scoring constants       | REWRITE   | `REVIEW_CONFIDENCE` is documented at `conflate.py:84–96`; the `_T_REV` alias is declared inline at `web/server.js:294` (`REVIEW_CONFIDENCE as _T_REV`). The real gap is composite scoring across CAGIS+TIGER (see R5.3). |
| R5.3  | Composite confidence cascade                | ACCEPT    | Per-source `cagis_match.confidence` and TIGER confidence aren't fused into a single way score. |
| R6.1  | Codecov in CI                               | ACCEPT    | `pytest-cov` is in `pyproject.toml` dev deps but `ci.yml:43` runs `pytest tests/ -v --tb=short` with no `--cov`. |
| R6.2  | E2E scan→submit test                        | ACCEPT    | Worth adding. **Caveat**: the report's example imports `osm.review.proposed_fixes_for_way`, which does not exist; redo against the real API. |
| R6.3  | API integration tests via supertest         | REWRITE   | No Node test harness exists today. First add the harness (jest/vitest + supertest), *then* the tests. |

## Section-by-Section Notes

### Section 1 — Frontend (ACCEPT)

All three claims hold. The monolith count, the `window.atlas*` coupling,
and the absence of a build pipeline are all real. R1.1, R1.2, R1.3 can
proceed as written.

### Section 2 — Python packaging (REJECT, with one survivor)

The report's premise — "no `setup.py`, `pyproject.toml`, or `__init__.py`" —
is contradicted by the working tree:

- `pyproject.toml` exists at repo root (modern setuptools layout).
- `src/osm/__init__.py` exists.
- `src/osm/transit.py:209–232` documents and implements a Windows fallback:
  the comment at line 210 explicitly says *"on platforms without fcntl"*,
  the `try: import fcntl` is at line 215, and the unlocked-write path is
  taken when import fails.

R2.1 and R2.2 should be dropped from any follow-up PR. R2.3 (CI matrix)
is the only Section 2 item with a real defect, but the framing needs
correction:

- The current matrix is `ubuntu-latest` × `["3.12", "3.13"]`.
- The report's proposed matrix lists Py 3.9, which the project has already
  moved past. A correct ask is "add `windows-latest` and `macos-latest`
  legs to the existing 3.12/3.13 matrix" — not "add a matrix from scratch".

### Section 3 — API & timeouts (ACCEPT)

All three findings hold:

- 5-minute hardcoded timeout (`web/server.js:140`).
- Synchronous `/api/scan` with no progress channel.
- `safeError()` is a one-line string trim.

R3.1, R3.2, R3.3 can proceed as written. The structured-error schema in
R3.3 should also include the `code` field the report proposes (e.g.
`TIMEOUT`, `MISSING_DEPS`) so the frontend can branch on it without
substring matching.

### Section 4 — Cache (ACCEPT)

No `/api/cache/*` endpoints exist. CAGIS (90d) and history (7d) TTLs are
declared as constants in `conflate.py:73` and `history.py:18` but are not
exposed to the UI. R4.1 is the highest-leverage item in this group; R4.2
is a small follow-on; R4.3 is nice-to-have.

### Section 5 — Conflation (ACCEPT R5.1, REWRITE R5.2, ACCEPT R5.3)

**R5.1 — accepted with a precision fix.** The report says shapely-missing
"silently degrades". The Python module is *not* silent — `conflate.py:166`
emits a `log.warning(...)`. But the web layer (`server.js:283`) only
checks `if SHAPELY_AVAILABLE:` and skips conflation without forwarding
anything to the response, so the warning never reaches the operator's
browser. The fix is to surface the missing-shapely state in the scan
response payload, not to add logging that already exists.

**R5.2 — rewrite.** The report claims `_T_REV` / `REVIEW_CONFIDENCE` is
an "undocumented magic constant". Both are documented:

- `conflate.py:82–96` defines and explains `BUFFER_M`, `HIGH_CONFIDENCE`,
  `REVIEW_CONFIDENCE`, and `FALLBACK_BUFFER_M`.
- `web/server.js:294` declares the alias inline:
  `from osm.tiger2024 import (... REVIEW_CONFIDENCE as _T_REV, ...)`.
  The `_T_` prefix matches `_T_SHP` and `_T_ZONES` in the same import
  block — clearly meaning "tiger".

The real gap is the one R5.3 names: per-source confidences (CAGIS match
score, TIGER match score) are not fused into a single way-level
confidence number that downstream UI / changeset code can reason about.
Recast R5.2 as "add a composite confidence helper" and merge it with R5.3.

### Section 6 — Tests & CI (ACCEPT)

- 372 test functions across 19 files (verified).
- `pytest-cov` is a declared dev dep but is not invoked in `ci.yml:43`
  (`pytest tests/ -v --tb=short`).
- No coverage upload step.

R6.1 is straightforward and high-leverage. R6.2's example is fine in
principle but uses a function (`osm.review.proposed_fixes_for_way`) that
doesn't exist — when implementing, build the test against the real
review/changeset API. R6.3 needs a one-step prerequisite (introduce a
Node test runner) before the supertest examples make sense.

## Suggested Next Steps

Priority-ordered, no effort estimates (the report's were unsupported):

- **High** — R6.1 (Codecov in CI), R4.1 (cache visibility endpoints),
  R5.1 (forward shapely-missing to the UI), R3.3 (structured error
  responses with `code` field).
- **Medium** — R2.3 (extend CI matrix to Win/mac on Py 3.12/3.13),
  R1.1 / R1.2 (frontend modularization + event bus), R3.1 / R3.2 (timeout
  warnings + SSE progress).
- **Low** — R1.3 (esbuild bundle), R4.3 (cache content hashing), R5.2+R5.3
  merged (composite confidence helper).

## Notes for the Report Author

Three claims in the original report are contradicted by files that exist
in the tree (R2.1: `pyproject.toml`; R2.2: the `fcntl` fallback in
`transit.py`; R5.2: documentation around `REVIEW_CONFIDENCE`). When a
report fabricates absent files, every other claim becomes suspect and a
reader has to re-verify the entire document — which is what happened
here. Future revisions should generate citations directly from the live
tree (`grep -n` output is fine) and include the file path *and* line
number for every concrete claim.
