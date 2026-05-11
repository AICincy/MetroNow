# Explainers

Decompression docs for dense `CLAUDE.md` sections. Each explainer is
hand-written for two readers in priority order:

1. **Future-you** picking the project back up cold after time away.
2. **A fresh AI session** that needs to bootstrap context without
   re-deriving the architecture from `src/osm/`.

Built with the [`metronow-explainer`](../../.claude/skills/metronow-explainer/SKILL.md)
skill. Diagrams are Mermaid, rendered natively by GitHub. No VitePress,
no static-site generator, no toolchain.

## Index

- [`detector-taxonomy.md`](detector-taxonomy.md): why `classify()`
  emits two parallel tracks (mechanical-fix candidates vs. rider-impact
  findings), and why the split is the project's mechanical-edit safety
  perimeter.
- [`conflation-matcher.md`](conflation-matcher.md): directed-Hausdorff
  scoring against CAGIS centerlines, the three-term confidence score,
  the eight buckets (`MATCHED_HIGH` / `MATCHED_REVIEW` /
  `MATCHED_FALLBACK_REVIEW` / `MIXED_LOW` / F1 through F4), the fallback
  hard-cap at `REVIEW_CONFIDENCE`, and the `osm baseline-diff`
  asymmetric-promotion alert.
- [`osm-community-gating.md`](osm-community-gating.md): the four-step
  Phase 1 gating in dependency order (Minh outreach → `_cincyimport`
  account → wiki page → talk-us@ + 14-day window), what happens if
  you skip each step, and the seven changeset tags every mechanical
  edit must carry.
- [`phase-status.md`](phase-status.md): what each of the four phases
  delivers, what gates the transitions, why Phase 1 is human-action-blocked,
  and where the cross-cutting workstreams (MOTIS prototype, pre-flight
  automation, Transit App quota tooling) fit.
- [`zone-data-flow.md`](zone-data-flow.md): SORTA's web map → `ZONES`
  dict + per-zone GeoJSONs → Overpass bbox query → polygon clip →
  classifier. Why the bbox-and-polygon split matters (Forest Park 78%
  F1 → normal after the clip).
- [`routing-engine-dispatch.md`](routing-engine-dispatch.md): the
  matched call shape between BRouter (default, OSM-only) and MOTIS
  (opt-in, multi-modal), the `is_available()` probe, and the
  next-session dispatcher line in `route_diff.py`.
- [`conventions.md`](conventions.md): the seven `CLAUDE.md`
  conventions split into stylistic vs load-bearing, with the failure
  mode each load-bearing rule closes (path traversal, quota
  underrun, XSS, false "done" reports) and the code that implements
  the defense.
- [`oauth-pkce-flow.md`](oauth-pkce-flow.md): OAuth 2.0
  Authorization Code + PKCE flow with the OOB redirect URI, why
  `state` is unenforced (PKCE does the real CSRF protection), and
  the chmod-0600 token storage.
- [`history-filter.md`](history-filter.md): two-tier review-status
  analysis (UNREVIEWED / LIKELY_REVIEWED / INCONCLUSIVE); why
  `tiger:reviewed=no` is unreliable and what 22-tag set indicates
  meaningful review instead.
- [`preflight-checks.md`](preflight-checks.md): the 17 codified
  checks across 6 categories with PASS/FAIL/WARN/MANUAL statuses
  and what `MANUAL` exists for (items the program literally cannot
  introspect).
- [`maproulette-tasks.md`](maproulette-tasks.md): Phase 3
  escalation path for Class A/AB ways below the auto-submit
  threshold; per-task Markdown instructions; the GeoJSON Lines
  output format and `[lat, lon] → [lon, lat]` conversion.
- [`transit-quota.md`](transit-quota.md): Transit App quota
  preservation under the 5,000 calls/month allocation (uplifted
  2026-05-11 from the 1,500 public tier); the 80% budget cap; the
  three load-bearing ToS obligations ("Powered by Transit",
  User-Agent, 10-business-day pre-release notice).

## Candidate next topics

Both rounds of the original SKILL.md backlog are fully shipped (the
6-item first round + the 5-item second round). See that skill's
"Topic backlog" section for any new candidate topics when re-entry
pain on a new subsystem makes another explainer worth writing.

## Style

See `.claude/skills/metronow-explainer/SKILL.md`. Short version:

- Definition first, WHY second, rule third.
- One Mermaid diagram per explainer, load-bearing not decorative.
- Every behavioral claim links to `file:line` in the codebase.
- Active voice, no marketing tone, no "obviously" or "simply."
- Cap at one screen of scrolling per concept; split if it grows.
