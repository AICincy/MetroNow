# Skill: `metronow-css-review`

**Summary.** Audit MetroNow Atlas stylesheets in two locations: the
inline `<style>` block in `web/public/index.html`, and the external
`web/public/css/atlas-supplement.css` (components added at runtime
by atlas.js). Checks design-token compliance, responsive layout,
color-contrast (WCAG AA), and IBM Plex font usage.

## What it does

Applies the CSS-specific subset of standards:

- **Design tokens via CSS custom properties**: colors, spacing, font
  scale all defined as `--token-*` vars at the top of the inline
  `<style>` block. New rules MUST reuse them; no hardcoded hex /px
  values.
- **IBM Plex font family**: `IBM Plex Sans` (UI), `IBM Plex Mono`
  (code), `IBM Plex Serif` (rarely). Loaded from `fonts.googleapis.com`.
- **Warm-neutral editorial palette**: defined in tokens; new
  components inherit, don't introduce new color systems.
- **Responsive breakpoints via media queries**: mobile-first; the
  three established breakpoints are documented in the inline
  `<style>` comments.
- **Color contrast WCAG AA**: verified against the token palette.
  Blocker-level when failing.
- **No `!important` outside the design-token override layer**:
  Warning-level when used elsewhere.

## When to invoke

- "Review my styles"
- "Check the CSS"
- "Is this accessible" (color contrast)
- "Does this use the right tokens"
- A CSS file or `<style>` block is in scope for code review.

## What it produces

Standard review report with Blocker / Warning / Info findings, scoped
to the CSS under review.

## Related skills

- [`metronow-code-review`](metronow-code-review.md): umbrella.
- [`metronow-html-review`](metronow-html-review.md): paired since
  inline `<style>` lives in HTML.

## See also

- [`SKILL.md`](../../.claude/skills/metronow-css-review/SKILL.md)
- [`docs/web-architecture.md`](../web-architecture.md)
