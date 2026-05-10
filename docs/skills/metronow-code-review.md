# Skill: `metronow-code-review`

**Summary.** Unified code-review umbrella for the MetroNow Atlas
codebase. Routes to the per-language reviewer based on file type
(JS / HTML / CSS / Dockerfile), applies cross-cutting standards
(security, consistency, no dead code), and produces severity-classified
findings (Blocker / Warning / Info).

## What it does

For each file in scope, dispatches to the appropriate per-language
review skill via the `references/` files bundled with this skill:

- `.js` files → `references/javascript.md`
- `.html` files → `references/html.md`
- CSS (inline + external) → `references/css.md`
- `Dockerfile`, `.dockerignore` → `references/dockerfile.md`

Cross-cutting standards applied to every file:

- **Security (Blocker)**: no secrets, all `innerHTML` user-input
  through `escapeHtml()`, no hardcoded production URLs.
- **Consistency (Warning)**: IIFE scope, `$()` helpers, `state`
  object, `el()` factory; no new frameworks/build tools.
- **General (Warning)**: no commented-out code, no untracked
  TODO/FIXME, no dead code.

## When to invoke

- "Review this code" / "Audit the frontend / backend"
- "Check my PR"
- "Does this meet our standards"
- "What's wrong with this file"

For a multi-file PR, this is the entry point: it routes per file and
produces one combined report.

## What it produces

A single review report with:

- `## [File path or section]` per file
- `### Blockers` (must fix before merge)
- `### Warnings` (creates tech debt)
- `### Info` (suggestions)
- Total count and merge-readiness verdict at the end.

## Related skills

- [`metronow-javascript-review`](metronow-javascript-review.md)
- [`metronow-html-review`](metronow-html-review.md)
- [`metronow-css-review`](metronow-css-review.md)
- [`metronow-dockerfile-review`](metronow-dockerfile-review.md)

This umbrella delegates to all four; the per-language skills can be
invoked directly for targeted reviews.

## See also

- [`SKILL.md`](../../.claude/skills/metronow-code-review/SKILL.md)
- [`docs/explainers/conventions.md`](../explainers/conventions.md):
  load-bearing rules vs stylistic preferences.
