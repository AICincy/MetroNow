---
name: metronow-css-review
description: "Code review and quality standards for MetroNow Atlas CSS. Use this skill when auditing stylesheets, checking design token compliance, validating responsive layout, auditing color contrast, or when someone asks \"review my styles,\" \"check the CSS,\" \"is this accessible,\" or \"does this use the right tokens.\" CSS lives in two places: an inline `<style>` block in `web/public/index.html` and an external `web/public/css/atlas-supplement.css`. Design system uses IBM Plex fonts, warm-neutral editorial palette, and CSS custom properties. Repo: https://github.com/AICincy/MetroNow.git"
compatibility: CSS3, CSS Custom Properties, CSS Grid, Flexbox
---

# MetroNow Atlas CSS Audit Guide

Instructional reference for agents autonomously auditing and remediating MetroNow Atlas CSS. Styles live in two places: a large inline `<style>` block at the top of `web/public/index.html` and an external stylesheet at `web/public/css/atlas-supplement.css` for components added by `atlas.js`. There is no runtime style injection by `atlas-extras.js`.

Classify every finding:

- **Blocker** - Must fix before merge
- **Warning** - Should fix, creates tech debt
- **Info** - Suggestion for improvement

## 1. Architecture

CSS lives in:
- `<style>` block inside `web/public/index.html` (~1390 lines, including the `:root` token definitions)
- `web/public/css/atlas-supplement.css` (~526 lines) — components added by `atlas.js`

No preprocessor (SASS/SCSS/PostCSS). No CSS modules. No Tailwind. Pure CSS custom properties.

## 2. Design Tokens (Source of Truth)

These are the exact tokens from the source. Any hardcoded value that bypasses them is a **Blocker**.

```css
:root {
  /* Typography */
  --serif: "IBM Plex Serif", "Source Serif 4", Georgia, serif;
  --sans: "IBM Plex Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;

  /* Light theme: warm-neutral, editorial */
  --bg: #f6f4ef;
  --bg-elevated: #ffffff;
  --bg-sunken: #efece5;
  --bg-overlay: #ffffff;
  --ink: #1a1814;
  --ink-soft: #4a463e;
  --ink-mute: #847e72;
  --ink-faint: #b6b1a4;
  --line: #e2ddd1;
  --line-soft: #ebe7dc;
  --line-strong: #d3cdbe;

  /* MetroNow brand: Metro orange */
  --brand: #fa6800;
  --brand-soft: #ffe1cc;
  --brand-deep: #c44e00;

  /* Accent (data/map) */
  --accent: #2c5282;
  --accent-soft: #dde4ee;

  /* Defect classes: semantic */
  --cls-ab: #b3261e;    --cls-ab-bg: #f7e4e2;
  --cls-a: #c95211;     --cls-a-bg: #f9e6da;
  --cls-b: #1f4e8a;     --cls-b-bg: #dde4ee;
  --cls-c: #6b6356;     --cls-c-bg: #ece7da;

  /* Status */
  --ok: #2e6b3b;        --ok-bg: #dde9d8;
  --warn: #8a6307;      --warn-bg: #f5e9c5;
  --err: #a02018;       --err-bg: #f3dcd9;

  /* Elevation */
  --shadow-sm: 0 1px 2px rgba(20,18,14,0.06), 0 1px 1px rgba(20,18,14,0.04);
  --shadow-md: 0 6px 24px -8px rgba(20,18,14,0.18), 0 2px 6px rgba(20,18,14,0.08);
  --shadow-lg: 0 24px 60px -20px rgba(20,18,14,0.30), 0 4px 14px rgba(20,18,14,0.10);

  /* Radii */
  --r-sm: 4px;
  --r-md: 6px;
  --r-lg: 10px;

  /* Layout */
  --rail-l: 340px;      /* Left rail (zones/controls) */
  --rail-r: 380px;      /* Right rail (inspector) */
  --header-h: 52px;
  --dock-h: 56px;
}
```

**Dark mode overrides** (activated via `data-theme="dark"` on `<html>`):

```css
[data-theme="dark"] {
  --bg: #0e1014;
  --bg-elevated: #14171c;
  --bg-sunken: #0a0c0f;
  --ink: #ece9e2;
  --ink-soft: #c2bdb1;
  --ink-mute: #8a857a;
  --ink-faint: #4a463e;
  --line: #23272e;
  --line-soft: #1a1d22;
  --line-strong: #2f343c;

  --brand: #ff8a3d;
  --brand-soft: #3a2010;
  --brand-deep: #ffb37a;

  --cls-ab: #e76055;  --cls-ab-bg: #2c1a18;
  --cls-a: #e8854a;   --cls-a-bg: #2c1f15;
  --cls-b: #6b9bd1;   --cls-b-bg: #1a2735;
  --cls-c: #8a857a;   --cls-c-bg: #1c1e22;
}
```

## 3. Accent System (Dynamic Theming)

The tweaks panel overrides `--brand`, `--brand-deep`, `--brand-soft` at runtime via `document.documentElement.style.setProperty()`. Accent palettes defined in JS:

```javascript
const accents = {
  orange: { brand: "#fa6800", deep: "#c44e00", soft: "#ffe1cc", ... },
  amber:  { brand: "#e68a00", deep: "#b36b00", soft: "#fff0cc", ... },
  rust:   { brand: "#c54b28", deep: "#983a1f", soft: "#f3ddd5", ... },
  steel:  { brand: "#0050ef", deep: "#003ab3", soft: "#d6e0fc", ... },
  forest: { brand: "#008a00", deep: "#005c00", soft: "#d1ecd1", ... },
};
```

**Audit criteria:**
- **Blocker:** CSS that hardcodes `#fa6800` or any accent hex instead of referencing `var(--brand)`
- **Warning:** JS-side `CLASS_COLOR` constants (`{ AB: "#b3261e", ... }`) that duplicate CSS `--cls-*` tokens. These should read from `getComputedStyle()`.
- **Info:** The `drawZoneBoundary()` function already reads `--brand` via `getComputedStyle()`. Other JS color references should follow this pattern.

## 4. Layout System

The app shell uses CSS Grid:

```css
.app {
  display: grid;
  grid-template-rows: var(--header-h) 1fr;
  grid-template-columns: var(--rail-l) 1fr var(--rail-r);
  grid-template-areas:
    "header header header"
    "lrail  map    rrail";
  height: 100vh;
}

.app[data-rrail="closed"] {
  grid-template-columns: var(--rail-l) 1fr 0;
}
```

**Audit criteria:**
- **Blocker:** Fixed pixel widths outside the custom properties
- **Warning:** Missing responsive handling for mobile. Currently the grid assumes desktop-width viewport. No `@media` breakpoints exist in the source.
- **Info:** The `--rail-l: 340px` and `--rail-r: 380px` values are hardcoded. Consider clamp() or min() for smaller screens.

## 5. Component Class Patterns

Actual class names from the source (reference for auditing):

```
Header:      .app-header, .brand, .brand-mark, .brand-sub, .header-center
Status:      .status-pill, .status-dot, .status-dot.ok/.warn/.err/.scanning
Breadcrumb:  .crumb, .crumb-sep
Search:      .search-wrap, #search
Left rail:   .left-rail, .rail-header, .rail-section
Zone cards:  .zone-card, .zone-glyph, .zone-name, .zone-desc, .zone-stat
Scan:        .scan-row, #scanBtn, #scanLabel, #lastRun
Legend:       .float-card, .leg-item[data-class], .leg-line, .leg-dot
Stats:       .stat, .stat-v, .stat-l, .stat.ab/.a/.b/.gaps
Class list:  .class-row, .class-bar, .class-label, .class-desc, .class-count
Inspector:   .right-rail, .inspector-head, .insp-eyebrow, .insp-title, .insp-id, .insp-tags
Fix card:    .fix-card, .fix-eyebrow, .fix-desc, .fix-diff, .diff-row.add/.del
Tags:        .class-tag.ab/.a/.b/.c, .review-pill
KV list:     .kv-list, .kv-k, .kv-v
Editor:      .editor-link, .el-name, .el-sub
Dock:        .dock, .dock-btn[data-view], .dock-badge
Buttons:     .btn, .btn-brand, .btn-sm, .btn-row
Panels:      .overlay-panel, .panel-header, .panel-body
Console:     .console-panel, .cl-row, .cl-time, .cl-tag, .cl-msg
Toast:       .toast, .toast.show, .toast.ok/.error
Basemap:     .basemap-toggle, .bm-btn[data-base]
Tweaks:      .tweaks-panel, .seg[data-tweak], .seg-btn, .tweak-swatch
```

**Audit criteria:**
- **Warning:** New classes that don't follow the existing naming conventions (hyphenated, no BEM)
- **Warning:** Orphaned classes (defined in CSS but no longer referenced in HTML/JS)
- **Info:** The project uses flat class names, not BEM. Do not flag the absence of BEM.

## 6. Color Contrast

**Blocker audit:**
- `--ink-mute` (#847e72) on `--bg` (#f6f4ef): ~3.4:1. Passes for large text (18px+) but fails for body text. Verify it's only used for secondary/decorative text.
- `--ink-faint` (#b6b1a4) on `--bg` (#f6f4ef): ~1.9:1. Fails WCAG AA entirely. Must be used only for decorative/non-essential elements.
- `--brand` (#fa6800) on `--bg` (#f6f4ef): ~3.3:1. Fails for body text. Check it's only used for large text or non-text indicators.

## 7. Font Rendering

The source correctly applies font smoothing:

```css
html, body {
  font-feature-settings: "ss01", "cv11";
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

**Info:** `"ss01"` and `"cv11"` are IBM Plex OpenType features. Verify they render correctly in target browsers.

## 8. Print Styles

Print media styles are defined in the inline `<style>` block in `index.html`:

```css
@media print {
  .left-rail, .dock, .float-card, .map-toolbar, .basemap-toggle,
  .tweaks-panel, .toast, ... { display: none !important; }
}
```

`!important` is acceptable in print stylesheets. Do not flag it.

## 9. Leaflet Overrides

Leaflet injects its own CSS. When auditing Leaflet overrides:
- `!important` is acceptable and expected
- Verify overrides are scoped (e.g., `.leaflet-container` prefix)
- **Warning:** Leaflet CSS loaded from CDN (`unpkg.com/leaflet@1.9.4`). Pin the version. Do not use `@latest`.

## Review Output Format

```
## [File path or section]

### Blockers
1. [Line X] Description of issue
   Fix: suggested correction

### Warnings
1. [Line X] Description of issue

### Info
1. [Line X] Suggestion
```

End with summary count and merge-readiness verdict.
