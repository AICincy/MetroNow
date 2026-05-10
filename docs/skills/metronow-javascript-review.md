# Skill: `metronow-javascript-review`

**Summary.** Audit JavaScript files in the MetroNow Atlas codebase:
`web/public/js/atlas.js`, `web/public/js/atlas-extras.js`, and
`web/server.js`. Vanilla JS only (no framework, no JSX, no bundler);
findings classified Blocker / Warning / Info.

## What it does

Applies the JavaScript-specific subset of the project's standards:

- **IIFE pattern**: atlas.js wraps in an IIFE; new code follows.
- **No frameworks / bundlers**: vanilla JS only, no JSX, no Vite,
  no React. New deps need explicit discussion.
- **Global `state` object**: atlas.js's central state lives there;
  don't shadow with module-level vars.
- **Leaflet conventions**: markers, layers, controls follow Leaflet
  patterns; don't reinvent.
- **`escapeHtml()` is mandatory**: every user-string-into-`innerHTML`
  path must pass through it. Blocker-level if missing.
- **No `eval` / `Function()` / `unsafe-inline`**: strict CSP forbids.
- **Path construction in `server.js`**: must go through `zonePath()`
  for CodeQL `js/path-injection` cleanliness.

## When to invoke

- "Review this JavaScript"
- "Audit atlas.js" / "audit server.js"
- "Check this JS"
- A `.js` file is mentioned in a code-review context.

## What it produces

Standard review report with Blocker / Warning / Info findings, scoped
to the JS file under review.

## Related skills

- [`metronow-code-review`](metronow-code-review.md): umbrella that
  invokes this skill for `.js` files.
- [`metronow-html-review`](metronow-html-review.md): paired when the
  PR touches both layers.

## See also

- [`SKILL.md`](../../.claude/skills/metronow-javascript-review/SKILL.md)
- [`docs/explainers/conventions.md`](../explainers/conventions.md):
  `zonePath()` containment and `escapeHtml()` rationale.
- [`docs/web-architecture.md`](../web-architecture.md): the codebase
  this skill reviews.
