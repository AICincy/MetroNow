# Pre-flight checklist — first MetroNow changeset

Run this checklist on the day you intend to submit the first
mechanical-edit batch. Every item is a yes/no the maintainer can
answer themselves; nothing left implicit. If any item is **No**,
**stop**.

## Community gating (Phase 1a)

- [ ] OSM wiki page is published at
      `wiki.openstreetmap.org/wiki/Automated_edits/<account-name>` and
      contains the changeset-tag template, opt-out contact, and
      discussion-history section with real archive URLs.
- [ ] `talk-us@openstreetmap.org` post went out at least **14 days
      ago** and the maintainer has read every reply.
- [ ] `community.openstreetmap.org` topic was opened and cross-linked
      to the talk-us@ thread.
- [ ] Minh Nguyễn (`User:Mxn`) was contacted privately first per
      `03-minh-outreach.md` and has either responded with no
      objection, or responded and the response has been addressed in
      the wiki page.
- [ ] No unresolved comments or opt-out requests on either public
      thread or in OSM messages to `<account-name>`.

## Account hygiene

- [ ] OSM account `<account-name>` exists, follows the
      `_cincyimport` suffix convention, and its bio links to the wiki
      page.
- [ ] OAuth credentials are saved at `~/.config/osm/credentials.json`
      and a current token is at `~/.config/osm/token.json`.
      `osm auth status` returns `Authenticated`.
- [ ] `osm auth login` was last run within the last 7 days, OR the
      saved token's scope still includes `write_api`.
- [ ] `src/osm/config.py:WIKI_URL` matches the **published** wiki
      page URL exactly. (Default value is a placeholder — update
      before first submission.)

## Pipeline state

- [ ] Code is on the latest `main` and CI is green at HEAD.
- [ ] `pytest tests/ -q` passes locally.
- [ ] `ruff check src/` and `mypy src/osm/ --ignore-missing-imports`
      both report clean.
- [ ] The four zone polygons under `src/osm/zones/` are present and
      were last updated within the last 90 days (so SORTA's web map
      hasn't shifted underneath you).

## Scan freshness

- [ ] `osm scan --zone blue-ash-montgomery` (or the chosen first
      zone) was run within the last 7 days. Overpass cache age is
      acceptable; CAGIS cache is fresh (90-day TTL).
- [ ] `osm conflate --zone blue-ash-montgomery --baseline-manifest`
      was re-run after the latest scan. The baseline manifest under
      `osm-audit-blue-ash-montgomery/data/cagis_baseline_*.json`
      shows `MATCHED_HIGH` count consistent with the previous run
      (no sudden drop).
- [ ] **Pinned the CAGIS cache** for the first batch — no quarterly
      CAGIS update in flight that could shift confidences mid-batch.

## First-batch composition

- [ ] You've chosen exactly **10 fixes** for the first batch,
      hand-picked from the cleanest `set_maxspeed_cagis` candidates
      in Blue Ash (highest confidence, well-known streets, no nearby
      OSM Notes or Osmose flags).
- [ ] None of the 10 fixes are on a way that has been edited by
      another mapper in the last 30 days (check `osm history` in the
      review UI or look at the way's history on osm.org).
- [ ] None of the 10 fixes are on a way the public discussion called
      out as a corridor to leave alone.

## Dry-run verification

- [ ] `osm fix --zone blue-ash-montgomery --dry-run` was run and the
      printed osmChange diff was inspected by a human (not just the
      maintainer — ideally a second reviewer).
- [ ] The diff shows exactly the changeset tags listed in the wiki
      page: `comment`, `created_by`, `source`, `mechanical=yes`,
      `bot=yes`, `description=<wiki URL>`, `cagis:attribution=<...>`.
- [ ] No fix in the dry-run output has `requires_human_review=true`
      (all are CAGIS-verified at confidence ≥ 0.85).
- [ ] `osm fix-impact --zone blue-ash-montgomery --limit 10` was run
      against the same 10 fixes; BRouter's `summary.real` count
      indicates the fixes will measurably change routing (or that the
      `set_maxspeed_cagis`-only batch is correctly skipped because
      maxspeed doesn't perturb the routing graph).

## Production submission

- [ ] OSMCha subscription is set up for `<account-name>` and for the
      four zone polygons, with a notification channel the maintainer
      will check within 4 hours.
- [ ] The maintainer has at least 4 hours of clear time to monitor
      the submission.
- [ ] `osm fix --zone blue-ash-montgomery` (no `--dry-run`) is the
      command to be run next.

## After submission (run within 4 hours)

- [ ] OSMCha shows the new changeset and is not flagged as suspicious.
- [ ] No revert appeared.
- [ ] No `talk-us@` reply or OSM message arrived raising concern.
- [ ] The 10 ways are visible on osm.org with the expected tag values.

## At 72 hours

- [ ] Still no revert, no community concern, no automated flag.
- [ ] If clear, scale the next batch to ~50 elements.
- [ ] If concern surfaced, halt and respond. Do **not** submit the
      next batch without addressing the concern.

## At 14 days

- [ ] Continue ramp to ≤ 500 element batches per the community norm.
- [ ] DWG import-role request can be filed if planning to scale
      beyond ~1,000 fixes/hour (Phase 5 territory).

---

**A "No" anywhere above is a STOP.** The pipeline is engineered to
make the technical bits safe, but community trust is built through
the discipline of these checks — not through the speed of shipping.
The first changeset is a relationship, not a transaction.
