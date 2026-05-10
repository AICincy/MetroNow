# Pre-flight checks: codified Phase 1 readiness gate

**Summary.** `osm preflight --zone <key>` runs 17 codified checks
across 6 categories and prints a colored go/no-go table. Each check
returns one of four statuses: **PASS** (green, automated), **FAIL**
(red, blocks first changeset), **WARN** (yellow, soft block:
`--strict` escalates to FAIL), or **MANUAL** (blue, requires human
attestation). Exit codes are `0` clean, `1` on any FAIL, `2` on any
WARN with `--strict`. The intent is *not* full automation: community
publication and OSMCha-monitoring checks fundamentally require human
inspection and surface as MANUAL: but to **remove the cognitive
friction** of remembering which checklist items are codable, so the
maintainer hits the human-attestation pass with everything
auto-checkable already green.

---

## What this is

The pre-flight checklist exists as paste-ready Markdown at
[`docs/community-prep/04-pre-flight-checklist.md`](../community-prep/04-pre-flight-checklist.md).
It has ~30 line items grouped by concern (community gating, account
hygiene, pipeline state, scan freshness, fix-batch readiness,
monitoring). On submission day, every item is supposed to read "yes"
before the first changeset goes out.

Some items can be checked by code: "is the OAuth token present?",
"do the four community-prep drafts exist as files?", "is the wiki URL
constant updated from the placeholder?". Others fundamentally cannot:
"did Minh respond?", "is the talk-us@ thread quiet?", "did the
maintainer read every reply on community.osm.org?".

`osm.preflight` codifies the codable subset and surfaces the
remaining items as MANUAL so they don't get lost
([preflight.py:1-12](../../src/osm/preflight.py#L1-L12)).

## How it works

The runner produces one `Check` dataclass per item, with `name`,
`category`, `status`, and `detail`. The CLI prints them grouped by
category and computes the exit code from the worst status seen.

1. **Status taxonomy.** Four statuses defined as module-level
   constants
   ([preflight.py:43-46](../../src/osm/preflight.py#L43-L46)):
   `PASS` (green; automated check passed), `FAIL` (red; automated
   check failed; blocks first changeset), `WARN` (yellow; degraded
   condition; soft block by default, hard with `--strict`), `MANUAL`
   (blue; requires human attestation; never auto-PASS).
2. **Six categories.** Mirror the headings in the markdown checklist
   so the CLI output and the doc stay structurally aligned
   ([preflight.py:50-55](../../src/osm/preflight.py#L50-L55)):
   `CAT_COMMUNITY` (gating artifacts), `CAT_ACCOUNT` (OAuth + naming),
   `CAT_PIPELINE` (CI green, tests pass, lint clean),
   `CAT_SCAN` (Overpass + CAGIS cache freshness),
   `CAT_FIX` (selected batch shape + dry-run), `CAT_MONITORING`
   (OSMCha + revert-watch readiness).
3. **Each check is a function.** All functions return a single
   `Check` dataclass
   ([preflight.py:58-65](../../src/osm/preflight.py#L58-L65)). The
   pattern is: do the check, build the dict, return. No exceptions
   leak: a check that errors internally returns `FAIL` with a
   `detail` describing the error, so one broken check doesn't kill
   the run.
4. **Path helpers are centralized.** `_output_dir(zone_key)` →
   `osm-audit-<zone>/`, `_scan_results_path()` →
   `osm-audit-<zone>/scan-results.json`, `_zone_polygon_path()` →
   `src/osm/zones/<zone>.geojson`, `_newest_baseline_manifest()`
   discovers the most recent CAGIS baseline manifest by mtime
   ([preflight.py:72-92](../../src/osm/preflight.py#L72-L92)).
5. **`--strict` escalates WARN to FAIL.** Without `--strict`, exit
   code 0 ships even with WARNs (some WARNs are advisory: e.g., a
   scan that's 5 days old, still valid but stale-ish). With
   `--strict`, any WARN becomes a hard stop.
6. **MANUAL items never auto-PASS.** A check that requires human
   attestation (community publication, monitoring readiness)
   returns `MANUAL` with a `detail` instructing the maintainer what
   to attest. The CLI surfaces these as a separate "still needs
   acceptance" list so they're highly visible at the end of the run.

## The flow, visually

```mermaid
---
title: osm preflight: 17 checks across 6 categories, four status colors
---
flowchart LR
    Run["osm preflight --zone <key>"]

    subgraph CAT_COMMUNITY["Community gating"]
        direction TB
        C1["check_wiki_url_set"]
        C2["check_community_drafts_present"]
        C3["check_community_publication_attested<br/>(MANUAL)"]
    end

    subgraph CAT_ACCOUNT["Account hygiene"]
        direction TB
        A1["check_oauth_token_present"]
        A2["check_oauth_scope_includes_write_api"]
        A3["check_account_naming_convention"]
    end

    subgraph CAT_PIPELINE["Pipeline state"]
        direction TB
        P1["check_zone_polygon_present"]
        P2["check_pytest_passes"]
        P3["check_ruff_clean"]
    end

    subgraph CAT_SCAN["Scan freshness"]
        direction TB
        S1["check_scan_freshness"]
        S2["check_baseline_manifest_after_scan"]
        S3["check_auto_submit_pool_size"]
    end

    subgraph CAT_FIX["Fix-batch readiness"]
        direction TB
        F1["check_first_batch_curated<br/>(MANUAL)"]
        F2["check_dry_run_was_inspected<br/>(MANUAL)"]
        F3["check_route_impact_was_run"]
    end

    subgraph CAT_MONITORING["Monitoring + post-submission"]
        direction TB
        M1["check_osmcha_subscription<br/>(MANUAL)"]
        M2["check_post_submission_window_planned<br/>(MANUAL)"]
    end

    Decide{"Aggregate worst status<br/>(FAIL > WARN > MANUAL > PASS)"}
    Exit0((exit 0<br/>green or only<br/>MANUAL pending))
    Exit1((exit 1<br/>any FAIL))
    Exit2((exit 2<br/>any WARN<br/>with --strict))

    Run --> CAT_COMMUNITY & CAT_ACCOUNT & CAT_PIPELINE & CAT_SCAN & CAT_FIX & CAT_MONITORING
    CAT_COMMUNITY & CAT_ACCOUNT & CAT_PIPELINE & CAT_SCAN & CAT_FIX & CAT_MONITORING --> Decide
    Decide -- "no FAIL, no WARN" --> Exit0
    Decide -- "any FAIL" --> Exit1
    Decide -- "any WARN with --strict" --> Exit2

    classDef cat fill:#3a3a3a,stroke:#888,color:#eee
    classDef pass fill:#1f4d2b,stroke:#3b8c5a,color:#e8f3ec
    classDef fail fill:#5b3a1c,stroke:#a06632,color:#f5ead7
    class CAT_COMMUNITY,CAT_ACCOUNT,CAT_PIPELINE,CAT_SCAN,CAT_FIX,CAT_MONITORING cat
    class Exit0 pass
    class Exit1,Exit2 fail
```

*What this shows: the runner fans out into six category subgraphs,
each with its own checks, then aggregates into the exit code via
worst-status-wins. The two MANUAL checks are explicitly visible
(community publication attestation; monitoring + revert-plan
attestation) so they never get accidentally auto-PASSed. What this
hides: the per-check `detail` strings, the runtime cost of
`check_pytest_passes` (which actually runs the test suite), and the
JSON-export mode (`--json`) used by CI.*

## Why MANUAL exists as a separate status

The most tempting design is binary: either a check passes or fails.
Pre-flight has a third reality: items where the *truth* of the check
is fundamentally outside the program's introspection range.

- "Did Minh respond to the outreach email?" → the program has no
  inbox.
- "Is the talk-us@ thread quiet (no unresolved concerns)?" → the
  program doesn't read mailing lists.
- "Has OSMCha been configured to monitor the `_cincyimport`
  changesets?" → the program doesn't have OSMCha credentials.

Marking these as PASS-by-default is wrong (they could be unfinished),
and as FAIL-by-default is wrong (they may already be done). MANUAL
captures the truth: *the maintainer needs to attest before the run is
truly green*. The exit code treats MANUAL as not-blocking-but-pending,
mirroring the doc's intent.

## Edge cases and gotchas

- **`check_pytest_passes` actually runs the tests.** It's not a
  status query; it shells out to `pytest`
  ([preflight.py:277](../../src/osm/preflight.py#L277)). On a fresh
  checkout this can take 30+ seconds. Use the `--skip-pytest` flag
  when iterating on the checklist itself.
- **`check_ruff_clean` and `check_pytest_passes` can FAIL on
  unrelated changes.** A WIP edit to an unrelated file can flip
  these red even when the audit pipeline is fine. Don't run
  preflight on a dirty working tree expecting all green.
- **`config.WIKI_URL` defaulting to a placeholder is intentional.**
  The default `https://wiki.openstreetmap.org/wiki/Hamilton_County_TIGER_Audit`
  is a placeholder; the maintainer must update it before first
  submission. `check_wiki_url_set()` returns `MANUAL` rather than
  `FAIL` because the placeholder URL might happen to match the
  published page (unlikely but possible)
  ([preflight.py:105-128](../../src/osm/preflight.py#L105-L128)).
- **`_newest_baseline_manifest` returns `None` on first scan.**
  Before any baseline manifest is written, the
  asymmetric-promotion-check has nothing to diff against. The
  related check WARNs (not FAILs) on this case so a fresh-machine
  setup can still complete pre-flight.
- **The CLI is single-zone.** `osm preflight --zone <key>` runs for
  one zone at a time. To run all four zones, the maintainer scripts
  the loop. There is no `--all-zones` flag intentionally: the
  pre-flight is per-batch, not per-project.
- **MANUAL count never decreases on its own.** Every fresh run shows
  the same MANUAL items. Tracking which were attested is the
  maintainer's responsibility (and the markdown checklist's
  checkbox is the canonical record).
- **Exit code 2 is `WARN with --strict`.** Some CI integrations
  treat any non-zero as failure; some treat 1 as failure and other
  codes as success. Check your CI's expectation before relying on
  the difference.

## Code references

- [`src/osm/preflight.py:1-22`](../../src/osm/preflight.py#L1-L22):
  module docstring, CLI invocation, exit code reference.
- [`src/osm/preflight.py:43-46`](../../src/osm/preflight.py#L43-L46):
  status constants (PASS/FAIL/WARN/MANUAL).
- [`src/osm/preflight.py:50-55`](../../src/osm/preflight.py#L50-L55):
  six category constants.
- [`src/osm/preflight.py:58-65`](../../src/osm/preflight.py#L58-L65):
  `Check` dataclass.
- [`src/osm/preflight.py:72-98`](../../src/osm/preflight.py#L72-L98):
  path helpers (`_output_dir`, `_scan_results_path`,
  `_zone_polygon_path`, `_newest_baseline_manifest`,
  `_file_age_seconds`).
- [`src/osm/preflight.py:105`](../../src/osm/preflight.py#L105):
  `check_wiki_url_set()` (first community check; example of
  MANUAL-not-FAIL when the answer is "ambiguous").
- [`src/osm/preflight.py:129`](../../src/osm/preflight.py#L129):
  `check_community_drafts_present()` (file-presence check).
- [`src/osm/preflight.py:153`](../../src/osm/preflight.py#L153):
  `check_community_publication_attested()` (canonical MANUAL).
- [`src/osm/preflight.py:167`](../../src/osm/preflight.py#L167):
  `check_oauth_token_present()` (reads `TOKEN_PATH`).
- [`src/osm/preflight.py:197`](../../src/osm/preflight.py#L197):
  `check_oauth_scope_includes_write_api()` (parses the saved token).
- [`src/osm/preflight.py:235`](../../src/osm/preflight.py#L235):
  `check_account_naming_convention()` (the `_cincyimport` suffix).
- [`src/osm/preflight.py:277`](../../src/osm/preflight.py#L277):
  `check_pytest_passes()` (shells out to `pytest`).
- [`src/osm/preflight.py:311`](../../src/osm/preflight.py#L311):
  `check_ruff_clean()`.
- [`src/osm/preflight.py:342`](../../src/osm/preflight.py#L342):
  `check_scan_freshness()`.
- [`docs/community-prep/04-pre-flight-checklist.md`](../community-prep/04-pre-flight-checklist.md):
  the markdown source of truth that this module codifies.

## See also

- [`CLAUDE.md` § Layout / Operational](../../CLAUDE.md): `preflight.py`
  is listed as the codified first-changeset readiness gate.
- [`docs/explainers/osm-community-gating.md`](osm-community-gating.md):
  the four community-gating artifacts that the CAT_COMMUNITY checks
  validate.
- [`docs/explainers/oauth-pkce-flow.md`](oauth-pkce-flow.md): the
  OAuth flow that produces the token CAT_ACCOUNT checks.
- [`docs/explainers/conventions.md`](conventions.md): the
  audit-before-done convention is the "soft" version of pre-flight;
  pre-flight is the codified version.
- [`docs/explainers/phase-status.md`](phase-status.md): pre-flight
  is the gate between Phase 1 and the first changeset.
