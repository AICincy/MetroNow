---
name: metronow-explainer
description: Decompress MetroNow docs so future-you (and fresh AI sessions) can pick the project back up cold without re-deriving everything. Use when the user says docs are confusing, plain, dense, hard to follow, missing context, jargon-heavy, jump straight to conclusions, or are hard to come back to after time away; asks why something is the way it is; says they can't tell what a term means; asks for a walkthrough, explainer, primer, or context refresher; says a section assumes too much; or wants visual aids. Diagnoses missing-middle gaps (undefined jargon, unstated WHY, skipped bridge steps, prose where a picture is needed) and rewrites sections using a fixed template — definition first, then bridge steps, then a load-bearing diagram, then code citations. Outputs to docs/explainers/<topic>.md or in-place edits. No VitePress, no static-site generator — just markdown that GitHub renders.
when_to_use: "User says docs are confusing/plain/dense/jargon-heavy, asks for an explainer or walkthrough, asks why something is the way it is, says they can't follow a section after coming back to it, or wants visuals added"
allowed-tools: Read Edit Write Glob Grep Bash(git *)
---

# MetroNow Explainer

The MetroNow docs are accurate but unreadable on re-entry. CLAUDE.md is
dense by design — it's a fast-loading context manifest. The dense sections
don't decompress for the reader because the author (the same person
re-reading them three weeks later) had so much context when writing that
the bridge steps became invisible. This skill rebuilds the bridge.

## Audience

This skill writes for two readers, in priority order:

1. **Future-you** — the maintainer, returning to the codebase after time
   on a different project, without paged-in context. The success bar is
   "pick it back up in 5 minutes, not 5 hours."
2. **Fresh AI sessions** — Claude or another agent landing in the repo
   cold. Explainers should be short enough to load into context without
   bloating it, structured so the agent can quote-and-cite them.

It does **not** write for new contributors, OSM volunteers, or civic
stakeholders. The project is solo-maintained; there is no onboarding
audience. Skip the new-contributor framing, the marketing voice, the
"welcome aboard" tone. Talk to yourself, three weeks from now, after a
context wipe.

## The problem (with examples)

Read this CLAUDE.md line:

> Mechanical edits require wiki documentation, `talk-us@` discussion, and
> `_cincyimport`-convention account.

A doctoral engineer who has never touched OSM cannot act on this. What's a
mechanical edit? Why does it need a wiki page? What wiki? What's
`talk-us@`? Why a special account? What does `_cincyimport`-convention
mean? Each phrase is load-bearing jargon with no inline expansion.

Or this:

> Two parallel tracks. Both run in `classify()`; the second only emits to
> the "Rider-impact findings" panel — never to the mechanical-fix queue.

Why two tracks? What makes one safe to fix mechanically and the other
unsafe? "Rider-impact" findings are the ones that affect riders — wouldn't
those be the *most* important to fix? The rule is stated; the reasoning
behind it (and the consequence of breaking it) is missing.

The pattern is consistent across `CLAUDE.md`, `docs/community-prep/*.md`,
and `docs/review/*.md`: the author knows so much that the in-between
context has become invisible to them. The reader gets the conclusion
without the steps that justify it.

## Diagnosis — five gap types

When asked to fix a section, identify which of these gaps it has.
Most confusing sections have at least three.

| Gap type | Symptom | Fix |
|---|---|---|
| **Undefined jargon** | Acronyms, project-specific terms, third-party tool names appear without expansion or link | Inline definition on first use, parenthetical for the rest |
| **Unstated WHY** | A rule is stated as a rule with no consequence-of-breaking-it | Add a "because otherwise…" clause, or a "this matters because…" sentence |
| **Skipped bridge steps** | The doc jumps from a concept to a constant or from a problem to a fix without showing the path | Numbered list of intermediate steps, each with a one-line rationale |
| **Prose where a picture is needed** | More than 3 entities interacting, a state machine, a decision tree, or time-ordered messages | Mermaid block — see the Mermaid house style section below and `docs/explainers/detector-taxonomy.md` for a worked reference |
| **Uncited claim** | "X works this way" with no `file:line` reference to verify or update against | Add a code-references list at the end of the explainer |

## Fix protocol

For each confusing section, apply this template — in this order:

1. **Define every load-bearing term** the first time it appears. One
   sentence, plus a link to the canonical source if external.
2. **State the WHY** before the WHAT. What problem does this solve? What
   would happen without this rule?
3. **Walk the bridge steps** as a numbered list. Each step gets one line
   of rationale.
4. **Insert a diagram** if there are 3+ entities, a state machine, a
   decision tree, or a time-ordered exchange. Hand-write a Mermaid block
   following the house style section below; `docs/explainers/detector-taxonomy.md`
   is the reference example for subgraphs, edge labels, and `classDef`
   color semantics.
5. **Cite code** at the end: `file:line` references for every claim about
   behavior. This is what makes the explainer age with the codebase
   instead of going stale.
6. **Cap at one screen** of scrolling for the section. If you can't fit,
   split into two explainers and link.

## Output protocol

Two modes:

**Standalone explainer (preferred for high-traffic concepts):**

Create `docs/explainers/<hyphen-cased-topic>.md`. Required sections, in
order:

```markdown
# <Topic>

**One-sentence summary** (the thing this explains, in one line).

## What this is

Definition. Why it exists. What problem it solves.

## How it works

Bridge steps (numbered list, one rationale per step).

## Diagram

Mermaid block — one per explainer, load-bearing not decorative.
GitHub renders these natively; no toolchain needed.

## Edge cases and gotchas

What confuses people. What the rule does NOT say. Failure modes.

## Code references

- `path/to/file.py:NN` — what this file/line does for this concept
- ...

## See also

- Other explainers, CLAUDE.md sections, OSM wiki pages, etc.
```

**In-place rewrite (for short sections):**

Use `Edit` to replace the confusing paragraph with the same template,
collapsed: definition first sentence, why second sentence, then a
`>` blockquoted "rule" line, then the diagram if needed.

## Filename and prose conventions

- Hyphens, never underscores (project convention).
- Active voice. "MetroNow fetches…", not "MetroNow is fetched…"
- One concept per heading. If a heading has "and" in it, split it.
- Avoid "simply", "just", "obviously", "of course". They flag the exact
  places where the author skipped a bridge step.
- Define before you use. If you cannot define a term in the same
  paragraph, link out to a definition.
- No marketing voice. The reader is technical. Don't sell, explain.

## What good looks like

A section is fixed when:

- The maintainer, returning after weeks on something else, reads it once,
  top to bottom, without scrolling back or opening another doc to look
  up a term.
- They could restate the WHY in their own words after reading.
- The diagram (if present) carries 60-80% of the comprehension load —
  the prose adds detail but isn't required for the mental model.
- Every behavioral claim links to a code line that justifies it.

The reference benchmark is `docs/explainers/detector-taxonomy.md`. New
explainers should match its shape (summary → what this is → how it works
→ diagram → edge cases → code references → see also) and its citation
density.

## What to avoid

- **Do not regenerate CLAUDE.md or community-prep docs from scratch.**
  CLAUDE.md is a context-loading manifest, not an explainer; it's dense
  on purpose. Community-prep docs are policy artifacts. Build explainers
  *alongside* these as a navigation layer, don't replace them.
- **Do not write tutorials.** This is reference-explainer territory, not
  step-by-step guides. The closest existing skill for tutorials is
  `zone-audit`'s SKILL.md.
- **Do not paraphrase the OSM wiki.** Link to it. The OSM wiki is the
  canonical source for OSM terms, and our explainer should defer.
- **Do not auto-generate everything.** This is hand-curation. The whole
  point of rejecting the deep-wiki plugin was that auto-generated docs
  go stale. One well-curated explainer beats ten generated wiki pages.

## Mermaid house style

- Wrap every block with `---\ntitle: ...\n---` so the diagram has a
  caption that survives copy-paste.
- Use `flowchart TD` (top-down) for pipelines, `flowchart LR` for
  two-system handoffs, `stateDiagram-v2` for buckets/state machines,
  `sequenceDiagram` for time-ordered actor exchanges, `gantt` for
  schedule artifacts.
- Define one `classDef` block at the bottom and apply with `class A,B name`.
  Don't inline `style` directives.
- Cap at ~25 nodes per diagram. Beyond that, split.
- Cross-check every node label against the codebase. Module names,
  function names, file paths, constants must resolve via grep.
- See `docs/explainers/detector-taxonomy.md` for a reference Mermaid
  block that demonstrates subgraphs, edge labels, shape variants
  (`((circle))`), and a three-color `classDef` for safe / judgment /
  gate semantics.

## Topic backlog

Track shipped explainers and what's next. When the user asks for "more
explainers" without specifying a topic, take the next pending item.

**Shipped:**

- ✅ `docs/explainers/detector-taxonomy.md` — why `classify()` emits two
  parallel tracks and why the split is the mechanical-edit safety
  perimeter.

**Pending, in priority of confusion-on-re-entry:**

1. **Conflation matcher state** (`conflation-matcher.md`) — what
   conflation is, what F1–F4 buckets mean, why directed-Hausdorff beat
   symmetric, what the auto-submit vs review bands mean operationally.
2. **OSM community requirements** (`osm-community-gating.md`) — what
   mechanical edits are, why OSM treats them specially, what each of
   the four required steps does, what happens if you skip one.
3. **Phase status** (`phase-status.md`) — what each phase delivers,
   what gates transitions, why Phase 1 is human-action-blocked.
4. **Zone data flow** (`zone-data-flow.md`) — SORTA web map → zone
   GeoJSON → Overpass query → audit; why we keep both real polygons
   and the TIGER FIPS 39061 fallback.
5. **Routing engine dispatch** (`routing-engine-dispatch.md`) —
   BRouter default vs MOTIS opt-in, the `is_available()` probe.
6. **Conventions** (`conventions.md`) — why no underscores, why auto
   mode by default, why `zonePath()` containment guard, why
   `fcntl.flock`.
