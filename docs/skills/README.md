# Claude skill explainers

Each `.claude/skills/<name>/SKILL.md` is the canonical source: Claude
loads it directly when its trigger conditions match. The files in this
directory are human-readable companions: short, skim-friendly,
"what-it-is + when-to-invoke + what-it-produces" notes for future-you
and fresh AI sessions.

Skills group by purpose. Within each category, the order is "use this
one first" → "narrower / specialized."

## Audit & investigation

Run analysis without touching OSM. Read-only against the audit
pipeline's outputs.

- [`zone-audit`](zone-audit.md): full TIGER defect audit pipeline for
  one zone (fetch → classify → history → reports).
- [`cagis-conflate`](cagis-conflate.md): cross-reference OSM against
  CAGIS quarterly road centerlines and ODOT TIMS.
- [`ground-truth-diff`](ground-truth-diff.md): diff OSM geometry +
  attributes against TIGER/Line 2024 to find import drift and name-field
  artifacts.
- [`tiger-history-deep`](tiger-history-deep.md): deep revision-history
  analysis for a specific OSM way (was it meaningfully reviewed?).
- [`osmcha-monitor`](osmcha-monitor.md): OSMCha changeset monitoring
  (post-submission via REST, pre-submission scoring locally).

## Submission & community

Touches OSM or community channels. Read these before any first-batch
submission.

- [`community-prep`](community-prep.md): prepare the four mandatory
  Phase 1 artifacts (wiki page, talk-us@ post, account, changeset
  templates). **Mandatory; not optional.**
- [`changeset-submit`](changeset-submit.md): submit corrections to OSM
  API v0.6 with full community compliance (tags, size limits, dry-run).
- [`maproulette-challenge`](maproulette-challenge.md): generate a
  MapRoulette challenge for findings with > 5% expected false-positive
  rate.

## Code review

Audits source files; produces severity-classified findings (Blocker /
Warning / Info).

- [`metronow-code-review`](metronow-code-review.md): umbrella that
  routes to the per-language reviews below based on file type.
- [`metronow-javascript-review`](metronow-javascript-review.md): JS
  audit (atlas.js, atlas-extras.js, server.js).
- [`metronow-html-review`](metronow-html-review.md): HTML audit (the
  single-file `web/public/index.html` shell).
- [`metronow-css-review`](metronow-css-review.md): CSS audit (inline
  `<style>` block + `web/public/css/atlas-supplement.css`).
- [`metronow-dockerfile-review`](metronow-dockerfile-review.md):
  Dockerfile / compose / container config audit.

## Documentation

- [`metronow-explainer`](metronow-explainer.md): produce the
  decompression explainers in `docs/explainers/` for dense `CLAUDE.md`
  sections. The skill that wrote everything in `docs/explainers/`.

## How to use

Most skills auto-invoke when their `description` field's trigger
phrases match the user's message. To force invocation, use
`/<skill-name>` in chat (e.g. `/zone-audit blue-ash-montgomery`).

To add a new skill: drop `<new-name>/SKILL.md` under `.claude/skills/`,
add the canonical description to the YAML frontmatter (clear trigger
phrases), then add a short explainer here following the same template.
