# MetroNow Atlas HTML Audit Guide

MetroNow Atlas HTML audit criteria. Severity levels defined in parent SKILL.md.

Instructional reference for agents autonomously auditing and remediating MetroNow Atlas HTML. The shipping app is:

- `web/public/index.html` (~1815 lines) - Main app shell with inline `<style>` block and external `<script>` tags pointing to `js/atlas.js` and `js/atlas-extras.js`.

Non-shipping HTML reports also live in `docs/` (`metronow-atlas.html`, `independent-audit.html`, `change-log.html`). These are static documentation, not the runtime app.

Classify every finding:

- **Blocker** - Must fix before merge
- **Warning** - Should fix, creates tech debt
- **Info** - Suggestion for improvement

## 1. Document Structure

The HTML file has this structure:

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>MetroNow Atlas — TIGER Audit Console</title>
  <!-- Google Fonts: IBM Plex Sans/Serif/Mono -->
  <!-- Leaflet CSS from unpkg CDN -->
  <style>/* ~800+ lines inline CSS */</style>
</head>
<body>
  <div id="app" class="app" data-rrail="closed">
    <!-- header, left-rail, map, right-rail, dock, panels -->
  </div>
  <div id="toast" class="toast"></div>
  <!-- Leaflet JS from unpkg CDN -->
  <script src="js/atlas.js"></script>          <!-- ~2072 lines -->
  <script src="js/atlas-extras.js"></script>   <!-- ~132 lines -->
</body>
</html>
```

**Audit criteria:**
- **Blocker:** Missing `<!DOCTYPE html>`, `lang` attribute, `charset`, or viewport meta
- **Warning:** Scripts loaded from CDN without `integrity` (SRI) attributes
- **Info:** The `<template id="__bundler_thumbnail">` block is for preview rendering. It's valid HTML5.

## 2. App Shell Grid Layout

```html
<div id="app" class="app" data-rrail="closed">
  <header class="app-header">...</header>
  <aside class="left-rail">...</aside>
  <div id="map">...</div>
  <aside id="rrail" class="right-rail">...</aside>
  <nav class="dock">...</nav>
  <!-- overlay panels -->
</div>
```

**Audit criteria:**
- **Warning:** The `#app` wrapper is a `<div>`, not a landmark. Acceptable since `<header>`, `<aside>`, and `<nav>` provide landmarks inside it.
- **Blocker:** If new sections are added without proper landmark elements
- **Warning:** The map container (`<div id="map">`) has no `role` or `aria-label`. Should have `role="application"` or `role="img"` with an `aria-label`.

## 3. Header Markup

```html
<header class="app-header">
  <div class="brand">
    <div class="brand-mark">MetroNow<em>!</em> Atlas</div>
    <div class="brand-sub">HAMILTON CO · TIGER AUDIT</div>
  </div>
  <div class="header-center">
    <div class="status-pill" id="apiStatus">
      <span class="status-dot" id="apiDot"></span>
      <span id="apiText">Checking…</span>
    </div>
    <div class="crumb">Zone <span class="crumb-sep">›</span> <span id="crumbZone">—</span></div>
  </div>
  <div class="header-end">
    <div class="search-wrap"><input id="search" type="text" placeholder="Search streets, way IDs…" /></div>
    <button id="authChip" class="auth-chip">...</button>
    <button id="tweaksBtn" class="icon-btn" title="Appearance">...</button>
  </div>
</header>
```

**Audit criteria:**
- **Warning:** `brand-mark` uses a `<div>` instead of `<h1>`. The page title should be a heading element.
- **Warning:** Search input `type="text"` should be `type="search"` for semantic correctness.
- **Warning:** Search input has no associated `<label>`. Add `aria-label="Search streets, way IDs"` or a `<label class="sr-only">`.
- **Warning:** Breadcrumb (`crumb`) uses `<div>` and `<span>` instead of `<nav aria-label="Breadcrumb">` with `<ol>/<li>` structure.

## 4. Zone Cards

Zone cards are rendered by JS via the `el()` factory:

```javascript
const card = el("button", {
  class: "zone-card",
  "aria-pressed": sel ? "true" : "false",
  onClick: () => selectZone(z.id),
}, ...);
```

**Audit criteria:**
- Uses `<button>` (correct, natively keyboard accessible)
- Uses `aria-pressed` for selection state (correct)
- **Info:** Zone cards are well-structured. No remediation needed for base pattern.

## 5. Legend and Filter Toggles

```html
<button class="leg-item" data-class="AB" aria-pressed="true">
  <span class="leg-line ab"></span><span>Compound</span><span id="legAB">0</span>
</button>
```

**Audit criteria:**
- Uses `<button>` with `aria-pressed` (correct toggle pattern)
- **Warning:** Defect counts update dynamically but the legend container lacks `aria-live="polite"`. Screen readers won't announce count changes.

## 6. Inspector (Right Rail)

Built entirely via `innerHTML` in `renderInspector()`:

```javascript
rail.innerHTML = `
  <div class="inspector-head">
    <div class="insp-eyebrow">Inspector · ${classLabel(cls)}</div>
    <h1 class="insp-title">${escapeHtml(name)}</h1>
    ...
  </div>
  <div class="kv-list">...</div>
  ${renderFixCard(w, cls)}
  <div class="editor-links">...</div>
`;
```

**Audit criteria:**
- **Warning:** `insp-title` uses `<h1>` but the page already has a brand heading. Should be `<h2>` or lower.
- **Blocker:** Verify all interpolated values in `innerHTML` pass through `escapeHtml()`. Check: `name`, `classLabel(cls)`, tag values, `fix.description`
- **Warning:** Fix card action buttons use `data-fix-action` attributes with delegated click handler on `#rrail`. This is correct but the buttons lack `aria-label` describing the action's target way.

## 7. Bottom Dock Navigation

```html
<nav class="dock">
  <button class="dock-btn" data-view="map">Map</button>
  <button class="dock-btn" data-view="results">Inventory</button>
  <button class="dock-btn" data-view="fix">Fix</button>
  <button class="dock-btn" data-view="investigate">Investigate</button>
  <button class="dock-btn" data-view="history">Ledger</button>
  <button class="dock-btn" data-view="discuss">Discuss</button>
  <button class="dock-btn" data-view="auth">Account</button>
</nav>
```

**Audit criteria:**
- Uses semantic `<nav>` (correct)
- **Warning:** Missing `aria-label="Main navigation"` since other `<nav>` elements may exist (breadcrumb, tools)
- **Warning:** Active tab needs `aria-current="page"` or `aria-selected="true"`
- **Info:** Dock badges are `<span class="dock-badge">` appended dynamically. Verify they have `aria-label` for count context.

## 8. Overlay Panels

```html
<div class="overlay-panel" id="resultsPanel">
  <div class="panel-header">
    <h2>Inventory</h2>
    <button data-close-panel aria-label="Close panel">×</button>
  </div>
  <div class="panel-body" id="resultsBody"></div>
</div>
```

**Audit criteria:**
- **Warning:** Panels lack `role="dialog"` and `aria-modal="true"` when open
- **Warning:** Focus should be trapped inside open panels (keyboard users can tab behind the panel)
- **Info:** Close button uses `×` character. Consider `aria-label="Close"` (already present in some panels, verify consistency).

## 9. Results Table

Built via `innerHTML` in `renderResultsPanel()`:

```html
<table class="t">
  <thead><tr><th>Class</th><th>Name</th><th>OSM ID</th>...</tr></thead>
  <tbody>
    <tr data-osm="12345">
      <td><span class="class-tag ab">AB</span></td>
      <td>Main Street</td>
      <td class="mono"><a href="https://www.openstreetmap.org/way/12345">12345</a></td>
      ...
    </tr>
  </tbody>
</table>
```

**Audit criteria:**
- **Warning:** Table rows are clickable via JS (`tr.onclick = ...`) but have no `role="button"`, `tabindex="0"`, or keyboard handler. Not keyboard accessible.
- **Warning:** External links to OSM have `target="_blank"` but some lack `rel="noopener"`. Verify all external links include it.
- **Info:** Table truncates at 400 rows with a message. Good UX but note the message is not an `aria-live` region.

## 10. CDN Dependencies

```html
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&..." />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
```

**Audit criteria:**
- **Warning:** CDN resources loaded without Subresource Integrity (`integrity` attribute)
- **Info:** `<link rel="preconnect">` for Google Fonts is present (correct)
- **Info:** Leaflet version pinned to 1.9.4 (correct, no `:latest`)
