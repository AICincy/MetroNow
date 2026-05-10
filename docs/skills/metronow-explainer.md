# Skill: `metronow-explainer`

**Summary.** Decompress dense `CLAUDE.md` sections (and other
documentation that confuses on cold re-entry) into hand-curated
explainers under `docs/explainers/`. The skill that produced every
file in that directory.

## What it does

Diagnoses missing-middle gaps in MetroNow docs and rewrites sections
using a fixed template:

1. **Definition first** — every load-bearing term gets an inline
   sentence on first use.
2. **WHY before WHAT** — what would happen without this rule? what
   problem does it solve?
3. **Bridge steps** — numbered list with one-line rationale per step.
4. **Load-bearing diagram** — Mermaid block when 3+ entities, a state
   machine, a decision tree, or a time-ordered exchange. Rendered
   natively by GitHub.
5. **`file:line` citations** — every behavioral claim links to code.
6. **Cap at one screen** of scrolling per concept; split if it grows.

Audience is **future-you** picking the project back up cold and
**fresh AI sessions** that need to bootstrap context without
re-deriving from `src/osm/`. Not for new contributors (none exist) —
skip the welcome-aboard tone.

## When to invoke

- "The docs are confusing / plain / dense / hard to follow"
- "Walkthrough" / "explainer" / "primer" / "context refresher"
- "Why is X the way it is?"
- "I can't follow this section after coming back to it"
- "Add visuals" / "this needs a diagram"

## What it produces

A new file at `docs/explainers/<topic>.md` with:

- One-sentence summary at the top.
- `## What this is`, `## How it works`, `## The flow, visually`,
  `## Edge cases and gotchas`, `## Code references`, `## See also`.
- A Mermaid diagram (if topic warrants one).
- 10–20 `file:line` citations.

Plus a one-line cross-link added to `CLAUDE.md` from the corresponding
dense section, and an entry added to `docs/explainers/README.md`'s
Index.

## Related skills

- All other skills produce *workflows*; this skill produces
  *documentation*. It's the meta-skill for the docs surface.

## See also

- [`SKILL.md`](../../.claude/skills/metronow-explainer/SKILL.md) —
  canonical source, including the "fix protocol" template, Mermaid
  house style, and topic-backlog tracking.
- [`docs/explainers/`](../explainers/) — every output of this skill.
- [`docs/explainers/README.md`](../explainers/README.md) — the Index
  this skill maintains.
