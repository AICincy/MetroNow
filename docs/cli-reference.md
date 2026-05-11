# `osm` CLI reference

The `osm` console entry point (Click-based) lives in `src/osm/cli.py`
and exposes 17 subcommands grouped by lifecycle stage. Run
`osm --help` for the live, source-of-truth listing; this doc is a
human-readable guide that explains each command's role in the audit
pipeline.

---

## Quick reference

| Command | Stage | What it does |
|---|---|---|
| `osm auth login` | Auth | Interactive OAuth 2.0 + PKCE login; saves token to `~/.config/osm/token.json` |
| `osm auth status` | Auth | Print authenticated username + token scope (none if logged out) |
| `osm scan` | Audit | Full pipeline: Overpass → polygon clip → classify → history filter → reports |
| `osm conflate` | Audit | Match scan's ways against CAGIS centerlines; annotate `cagis_match` |
| `osm conflate-tiger` | Audit | Same but using TIGER 2024 as fallback ground truth |
| `osm baseline-diff` | Audit | Compare two CAGIS baseline manifests; flag asymmetric-promotion regressions |
| `osm route-diff` | Audit | Run BRouter perturbation against detector findings to filter false positives |
| `osm fix-impact` | Audit | Per-fix BRouter route comparison (length / duration delta) |
| `osm notes` | Audit | Fetch OSM Notes for the zone bbox; cache locally |
| `osm osmose` | Audit | Fetch Osmose-QA issues for the zone bbox |
| `osm preflight` | Gate | Run the 17 codified pre-flight checks; PASS/FAIL/WARN/MANUAL |
| `osm fix` | Submit | Apply CAGIS-verified fixes via OSM API v0.6 (**NOT** default-dry-run; pass `--dry-run` explicitly to preview) |
| `osm maproulette` | Submit | Generate per-zone MapRoulette challenge GeoJSON Lines |
| `osm transit-status` | Status | Transit App quota + cache state |
| `osm transit-budget` | Status | Per-day budget recommendation given remaining quota |
| `osm motis-status` | Status | MOTIS instance reachability probe |
| `osm report` | Output | Re-render the dashboard / XLSX / CSVs from existing scan results |

`--help` works at every level: `osm --help`, `osm scan --help`,
`osm auth --help`, etc.

## By stage

### Auth

```
osm auth login
osm auth status
```

`login` opens a browser to the OSM authorization endpoint, prompts for
the OOB authorization code paste, exchanges via PKCE, and saves to
`~/.config/osm/token.json` with chmod 0600. `status` reads the saved
token and reports the authenticated username + scope.

See [`docs/explainers/oauth-pkce-flow.md`](explainers/oauth-pkce-flow.md)
for the flow detail and why `state` is unenforced.

### Audit (read-only, no OSM writes)

```
osm scan --zone <key> [flags]
osm conflate --zone <key> [--force-refresh] [--baseline-manifest]
osm conflate-tiger --zone <key> [--force-refresh] [--all-ways]
osm baseline-diff --zone <key> [--from <path>] [--to <path>]
osm route-diff --zone <key> [--profile car-fast] [--limit N]
osm fix-impact --zone <key> [--profile car-fast] [--limit N]
osm notes --zone <key> [--force-refresh] [--status open|all]
osm osmose --zone <key> [--force-refresh] [--item ITEM_CODE]...
```

**`osm scan`** is the workhorse: it runs the entire audit pipeline
end-to-end and writes `osm-audit-<zone>/scan-results.json`. Notable
flags:

| Flag | Effect |
|---|---|
| `--zone <key>` | One of `blue-ash-montgomery`, `springdale-sharonville`, `northgate-mt-healthy`, `forest-park-pleasant-run`, or `all` |
| `--from-cache` | Use cached Overpass data; skip live query |
| `--skip-history` | Use legacy `tiger:reviewed=no` mode (faster but less accurate) |
| `--import-only` | Filter to ways still on their original TIGER import version (smaller, high-confidence subset) |
| `--with-conflation` | Run `osm.conflate` inline (otherwise call `osm conflate` after) |
| `--tiger-only` | Skip CAGIS, use TIGER 2024 only (for incomplete CAGIS coverage) |
| `--with-route-diff` | Run BRouter false-positive filtering inline |
| `--with-gtfs-cross-check` (default on) | Validate `highway=bus_stop` nodes against SORTA GTFS |
| `--with-bus-route-corroboration` (default on) | Annotate `oneway_conflicts` findings with `transit_corridor=True` when on a CAGIS bus-route corridor |
| `--with-transit-cross-check` (default on) | Cross-check `misplaced_bus_stops` findings against Transit App's nearby-stops data (one API call per flagged stop); a finding Transit corroborates within 50 m is suppressed. No-ops without a Transit API key; consumes Transit monthly quota |
| `--include-unnamed-service` | Include unnamed `highway=service` ways (off by default to reduce noise) |

**`osm conflate`** annotates an existing scan's `all_ways` with
`cagis_match` dicts. `--force-refresh` re-downloads CAGIS centerlines
even if the 90-day cache is fresh. `--baseline-manifest` writes a
snapshot under `osm-audit-<zone>/data/cagis_baseline_*.json` for
later comparison via `osm baseline-diff`. See
[`docs/explainers/conflation-matcher.md`](explainers/conflation-matcher.md).

**`osm baseline-diff`** compares two manifests and flags
*asymmetric-promotion* violations: `MATCHED_HIGH` growth sourced from
`MATCHED_REVIEW` contraction rather than from `F3_GEOMETRY_FAIL`
reduction. The default behavior (no `--from` / `--to`) discovers the
two most recent manifests by mtime.

**`osm route-diff` and `osm fix-impact`** both use BRouter, but
differently. `route-diff` runs perturbation tests against the
rider-impact detectors to filter false positives; `fix-impact`
measures the per-fix routing delta (length, duration) between the
live OSM graph and the post-fix simulated graph. Both honor
`--profile` (BRouter profile name; default `car-fast`) and
`--limit N` (cap how many findings to test).

**`osm notes` and `osm osmose`** fetch and cache the respective
external feeds for a zone. Both are run automatically as part of
`osm scan` when relevant flags are set; explicit invocation is for
cache warming or debugging. See
[`docs/explainers/external-feeds.md`](explainers/external-feeds.md).

### Gate

```
osm preflight --zone <key> [--strict] [--skip-pytest]
```

Runs the 17 codified pre-flight checks. Exit codes:

- `0`: all PASS or only MANUAL items pending
- `1`: at least one FAIL (stop and fix)
- `2`: at least one WARN, and `--strict` was set

`--skip-pytest` short-circuits `check_pytest_passes` (which actually
shells out to pytest and takes 30+ seconds on a fresh checkout).

See [`docs/explainers/preflight-checks.md`](explainers/preflight-checks.md).

### Submit (writes to OSM or to MapRoulette)

```
osm fix --zone <key> [--dry-run] [other flags]
osm maproulette --zone <key> [--kind class-a|gaps|both] [--out <path>]
```

**`osm fix`** is the only command that actually writes to OSM.
**`--dry-run` is opt-in, not the default.** Without the flag, the
command will open a real changeset and submit. Always pass
`--dry-run` first to preview the changeset XML; only run without it
once you've reviewed the dry-run output and the four-step community
gating is complete. See
[`docs/explainers/osm-community-gating.md`](explainers/osm-community-gating.md)
for the seven changeset tags this command emits and the four-step
gating that must precede first-batch submission.

**`osm maproulette`** writes a `.geojsonl` file under
`osm-audit-<zone>/maproulette/`: one MapRoulette task per OSM way
with a Markdown instruction. `--kind` accepts `class-a` (default;
Class A/AB ways below the auto-submit threshold), `gaps`
(node-disconnect candidates), or `both` (writes two separate
`.geojsonl` files plus two metadata payloads). See
[`docs/explainers/maproulette-tasks.md`](explainers/maproulette-tasks.md).

### Status (read-only diagnostics)

```
osm transit-status
osm transit-budget [--calls N] [--per-day]
osm motis-status [--probe]
```

**`osm transit-status`** reports the Transit App quota state: API key
present? this month's usage so far? remaining within the 80% budget?
**`osm transit-budget`** suggests how many calls are safe per day for
the rest of the month, given the remaining quota and days left.
`--calls N` overrides the assumed per-day demand; `--per-day` formats
output as a daily allocation.

**`osm motis-status`** reads `MOTIS_BASE` (default
`http://localhost:8080`) and reports configuration; with `--probe`,
also calls `is_available()` to check that an instance answers. See
[`docs/explainers/routing-engine-dispatch.md`](explainers/routing-engine-dispatch.md)
and [`docs/explainers/transit-quota.md`](explainers/transit-quota.md).

### Output

```
osm report --zone <key>
```

Re-renders the XLSX workbook, the Leaflet dashboard HTML, and the
four CSV slices from an existing `scan-results.json`. Useful when
the report-rendering code changes and you want fresh outputs without
re-running the full pipeline.

## How it's wired

The CLI is a single Click `Group` rooted at
[`src/osm/cli.py:37`](../src/osm/cli.py#L37) (`def main(verbose)`).
Each subcommand is `@main.command()` (or `@main.command(name="...")`
for hyphenated names that don't translate cleanly from Python
identifiers).

Auth subcommands live under a nested Click group at
[`src/osm/cli.py:49`](../src/osm/cli.py#L49) (`def auth()`); the
hyphenless commands `auth login` / `auth status` are under it.

Run `python -m osm <subcommand>` if `osm` isn't on PATH (the
console-script entry point depends on a clean install).

## Patterns to follow when adding a command

1. **Use `@main.command()` (or `@main.command(name="hyphenated")`).**
   Don't make a fresh top-level `@click.command` outside the group.
2. **Default `--zone` to `DEFAULT_ZONE` from `osm.zones`.** Use
   `click.Choice(ZONE_KEYS)` for validation; `click.Choice(ZONE_KEYS
   + ["all"])` if "all four zones" makes sense.
3. **`is_flag=True` for booleans, not `--enable-foo`/`--disable-foo`.**
   Use `--with-foo/--no-foo` paired form only when the default
   matters (per the `--with-bus-route-corroboration` pattern).
4. **One responsibility per command.** Don't bundle unrelated
   functionality. The split between `route-diff` and `fix-impact`
   is the canonical example: both use BRouter, but for different
   purposes; they're separate commands.
5. **Match the audit pipeline's data flow.** Audit commands read
   from disk (a prior scan); submit commands read from disk and
   call OSM API; status commands read from `~/.config/osm/`.

## Code references

- [`src/osm/cli.py:37`](../src/osm/cli.py#L37): `main()` Click group
  root.
- [`src/osm/cli.py:49`](../src/osm/cli.py#L49): `auth` subgroup.
- [`src/osm/cli.py:135`](../src/osm/cli.py#L135): `scan` (workhorse).
- [`src/osm/cli.py:459`](../src/osm/cli.py#L459): `fix` (only OSM
  writer).
- [`src/osm/cli.py:590`](../src/osm/cli.py#L590): `conflate`.
- [`src/osm/cli.py:685`](../src/osm/cli.py#L685): `conflate-tiger`.
- [`src/osm/cli.py:782`](../src/osm/cli.py#L782): `route-diff`.
- [`src/osm/cli.py:873`](../src/osm/cli.py#L873): `fix-impact`.
- [`src/osm/cli.py:991`](../src/osm/cli.py#L991): `baseline-diff`.
- [`src/osm/cli.py:1101`](../src/osm/cli.py#L1101): `maproulette`.
- [`src/osm/cli.py:1193`](../src/osm/cli.py#L1193): `transit-status`.
- [`src/osm/cli.py:1241`](../src/osm/cli.py#L1241): `transit-budget`.
- [`src/osm/cli.py:1307`](../src/osm/cli.py#L1307): `motis-status`.
- [`src/osm/cli.py:1361`](../src/osm/cli.py#L1361): `preflight`.
- [`src/osm/cli.py:1434`](../src/osm/cli.py#L1434): `report`.

## See also

- [`CLAUDE.md` § Layout / Plumbing](../CLAUDE.md): where `cli.py` is
  listed.
- [`docs/explainers/`](explainers/): per-subsystem explainers each
  cross-link back to the relevant subcommand.
- [`docs/skills/`](skills/): many skills wrap one or more of these
  subcommands as their primary action (e.g. `zone-audit` wraps
  `osm scan`; `cagis-conflate` wraps `osm conflate`).
- [Click documentation](https://click.palletsprojects.com/): the
  CLI framework.
