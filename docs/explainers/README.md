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

- [`detector-taxonomy.md`](detector-taxonomy.md) — why `classify()`
  emits two parallel tracks (mechanical-fix candidates vs. rider-impact
  findings), and why the split is the project's mechanical-edit safety
  perimeter.
- [`conflation-matcher.md`](conflation-matcher.md) — directed-Hausdorff
  scoring against CAGIS centerlines, the three-term confidence score,
  the eight buckets (`MATCHED_HIGH` / `MATCHED_REVIEW` /
  `MATCHED_FALLBACK_REVIEW` / `MIXED_LOW` / F1–F4), the fallback
  hard-cap at `REVIEW_CONFIDENCE`, and the `osm baseline-diff`
  asymmetric-promotion alert.
- [`osm-community-gating.md`](osm-community-gating.md) — the four-step
  Phase 1 gating in dependency order (Minh outreach → `_cincyimport`
  account → wiki page → talk-us@ + 14-day window), what happens if
  you skip each step, and the seven changeset tags every mechanical
  edit must carry.
- [`phase-status.md`](phase-status.md) — what each of the four phases
  delivers, what gates the transitions, why Phase 1 is human-action-blocked,
  and where the cross-cutting workstreams (MOTIS prototype, pre-flight
  automation, Transit App quota tooling) fit.
- [`zone-data-flow.md`](zone-data-flow.md) — SORTA's web map → `ZONES`
  dict + per-zone GeoJSONs → Overpass bbox query → polygon clip →
  classifier. Why the bbox-and-polygon split matters (Forest Park 78%
  F1 → normal after the clip).
- [`routing-engine-dispatch.md`](routing-engine-dispatch.md) — the
  matched call shape between BRouter (default, OSM-only) and MOTIS
  (opt-in, multi-modal), the `is_available()` probe, and the
  next-session dispatcher line in `route_diff.py`.

## Backlog (in priority of confusion-on-re-entry)


## Style

See `.claude/skills/metronow-explainer/SKILL.md`. Short version:

- Definition first, WHY second, rule third.
- One Mermaid diagram per explainer, load-bearing not decorative.
- Every behavioral claim links to `file:line` in the codebase.
- Active voice, no marketing tone, no "obviously" or "simply."
- Cap at one screen of scrolling per concept; split if it grows.
