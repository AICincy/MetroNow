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

## Backlog (in priority of confusion-on-re-entry)

- `osm-community-gating.md` — what mechanical edits are, why OSM
  treats them specially, what each of the four required steps does
  (wiki page, talk-us@, account convention, changeset tags), what
  happens if you skip one.
- `phase-status.md` — what each Phase 1–4 delivers, what gates the
  transitions, why Phase 1 is human-action-blocked.
- `zone-data-flow.md` — SORTA web map → `src/osm/zones/*.geojson` →
  Overpass query → audit. Why we keep both real operational polygons
  and the TIGER FIPS 39061 fallback.
- `routing-engine-dispatch.md` — BRouter default vs MOTIS opt-in,
  the `is_available()` probe, the future single-dispatcher line in
  `route_diff.py`.

## Style

See `.claude/skills/metronow-explainer/SKILL.md`. Short version:

- Definition first, WHY second, rule third.
- One Mermaid diagram per explainer, load-bearing not decorative.
- Every behavioral claim links to `file:line` in the codebase.
- Active voice, no marketing tone, no "obviously" or "simply."
- Cap at one screen of scrolling per concept; split if it grows.
