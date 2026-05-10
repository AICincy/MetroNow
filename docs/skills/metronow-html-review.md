# Skill: `metronow-html-review`

**Summary.** Audit HTML files — primarily the single-file
`web/public/index.html` shell that is the MetroNow Atlas frontend.
Checks accessibility (WCAG), semantic markup, and integration with
the inline `<style>` block + external script tags.

## What it does

Applies the HTML-specific subset of standards:

- **Semantic markup** — `<nav>`, `<main>`, `<section>`, `<header>`,
  `<footer>` over generic `<div>`s where applicable.
- **Accessibility (WCAG AA)** — every interactive element has an
  accessible name; ARIA attributes are correct (Blocker-level when
  WCAG-failing).
- **`escapeHtml()` boundary** — no untrusted text inserted via raw
  `innerHTML`. Cross-checked against the JS layer.
- **Inline `<style>` discipline** — atlas's inline CSS lives in one
  block at the top of `<head>`; runtime additions go via
  `web/public/css/atlas-supplement.css` (loaded by atlas.js).
- **External origin alignment** — every CDN reference (unpkg,
  fonts.googleapis.com, etc.) must appear in the helmet CSP allow-list
  in `web/server.js`.

The shipping app is `web/public/index.html` (~1856 lines). Several
non-shipping HTML reports live in `docs/`; reviewers should treat
those as throwaway artifacts (different standards apply).

## When to invoke

- "Review this page"
- "Check the markup"
- "Is this accessible"
- "Does this meet WCAG"
- A `.html` file is mentioned in a code-review context.

## What it produces

Standard review report with Blocker / Warning / Info findings, scoped
to the HTML file under review.

## Related skills

- [`metronow-code-review`](metronow-code-review.md) — umbrella.
- [`metronow-css-review`](metronow-css-review.md) — paired since the
  inline `<style>` block lives in HTML but is reviewed under CSS rules.

## See also

- [`SKILL.md`](../../.claude/skills/metronow-html-review/SKILL.md)
- [`docs/web-architecture.md`](../web-architecture.md)
