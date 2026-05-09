# JavaScript Audit Standards

MetroNow Atlas javascript audit criteria. Severity levels defined in parent SKILL.md.

# MetroNow Atlas JavaScript Audit Guide

Instructional reference for agents autonomously auditing and remediating MetroNow Atlas JavaScript. The codebase is vanilla JS, not a framework app. Do not suggest React/Vue/Angular refactors.

Classify every finding:

- **Blocker** - Must fix before merge
- **Warning** - Should fix, creates tech debt
- **Info** - Suggestion for improvement

## 1. Architecture Overview

The frontend is two JS files plus one JSX utility:

- `atlas.js` (~1639 lines) - Main app. IIFE with `"use strict"`. Contains all state, rendering, API calls, map logic, and event wiring.
- `atlas-extras.js` (~495 lines) - Enhancement layer. Adds keyboard shortcuts, bulk select, OSM-ID linkification, tools launcher. Uses DOM hooks only, no atlas.js internals.
- `tweaks-panel.jsx` (~568 lines) - Reusable React component for design tweaks panel. Loaded via Babel CDN. Only JSX in the project.

No build system. No bundler. No module imports. Scripts load via inline `<script>` tags in the HTML file.

## 2. State Management

Global `state` object at module scope inside the IIFE:

```javascript
const state = {
  apiOnline: false,
  zones: ZONE_FALLBACK.map(z => ({ ...z, wayCount: null })),
  zone: ZONE_FALLBACK[0].id,
  scan: null, scanning: false,
  scanStart: 0, scanTick: 0, scanES: null,
  selectedWay: null,
  filters: { AB: true, A: true, B: true, C: false, GAPS: true },
  basemap: "positron", view: "map",
  fixProposals: null, history: [],
  auth: { connected: false, name: null },
  tweaks: parseDefaultTweaks(),
  discuss: loadDiscuss(),
  formality: loadFormality(),
};
```

**Audit criteria:**
- **Blocker:** State mutations outside the IIFE scope
- **Warning:** Direct DOM state (e.g., using `element.dataset` as source of truth instead of `state`)
- **Warning:** Missing state reset in `selectZone()` when switching zones (check `state.scan`, `state.fixProposals`, `state.selectedWay` are all nulled)

## 3. DOM Helper Conventions

The codebase defines its own micro-framework:

```javascript
const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));
const el = (tag, props={}, ...kids) => { /* element factory */ };
```

**Audit criteria:**
- **Warning:** Using `document.getElementById()` or `document.querySelector()` instead of `$()` / `$$()` (inconsistent with codebase convention)
- **Warning:** Using `innerHTML` concatenation where `el()` factory would be safer (XSS surface)
- **Blocker:** Unescaped user input in `innerHTML`. The codebase has `escapeHtml()`. Verify every `innerHTML` assignment passes through it.

## 4. API Communication

All API calls go through the `api()` wrapper:

```javascript
async function api(path, opts={}) {
  const url = API + path;
  const res = await fetch(url, { ...opts, headers: { "Content-Type":"application/json", ...(opts.headers||{}) } });
  if (!res.ok) { /* throws with status + body excerpt */ }
  return ct.includes("json") ? res.json() : res.text();
}
```

**Audit criteria:**
- **Blocker:** Bare `fetch()` calls that bypass the `api()` wrapper (loses error handling, base URL, headers)
- Exception: `pingApi()` uses bare `fetch()` intentionally (catch block returns false)
- **Blocker:** Missing error handling around any `await api(...)` call
- **Warning:** Missing user feedback (toast) on API failure
- **Warning:** Missing `state.apiOnline` check before API calls

## 5. Rendering Pattern

Rendering is imperative. Functions like `renderZones()`, `plotScan()`, `renderInspector()`, `renderResultsPanel()` directly manipulate DOM:

```javascript
function renderZones() {
  const wrap = $("#zoneList");
  wrap.innerHTML = "";
  state.zones.forEach(z => {
    const card = el("button", { class: "zone-card", "aria-pressed": sel, onClick: ... }, ...);
    wrap.appendChild(card);
  });
}
```

**Audit criteria:**
- **Warning:** Render functions that don't clear the container before appending (causes duplicates)
- **Warning:** Missing `aria-pressed`, `aria-expanded`, or `role` attributes on interactive elements built via `el()`
- **Warning:** Event listeners attached inside render loops without cleanup (memory leak on re-render)
- **Info:** Large render functions (over 50 lines) that should be split

## 6. Defect Class Constants

```javascript
const CLASS_COLOR = { AB: "#b3261e", A: "#c95211", B: "#1f4e8a", C: "#6b6356" };
const WEIGHT = { thin: 2, med: 3, thick: 4.5 };
```

These correspond to the CSS variables `--cls-ab`, `--cls-a`, `--cls-b`, `--cls-c`. When auditing:
- **Warning:** Hardcoded hex colors in JS that diverge from CSS custom properties
- **Warning:** Using raw class strings (`"AB"`, `"A"`) instead of constants

## 7. Event Source (SSE) Scan Streaming

The scan uses `EventSource` for real-time console output:

```javascript
state.scanES = new EventSource(`${API}/api/scan/stream?zone=...`);
state.scanES.onmessage = ev => { /* parse JSON, log to console_ */ };
state.scanES.onerror = () => { state.scanES?.close(); state.scanES = null; };
```

**Audit criteria:**
- **Blocker:** EventSource not closed in the `finally` block of `runScan()`
- **Warning:** Missing reconnection logic or retry limits

## 8. LocalStorage Patterns

```javascript
const LS = {
  discuss: "metronow.atlas.discuss.v1",
  formality: "metronow.atlas.formality.v1",
  authorName: "metronow.atlas.author.v1",
};
```

**Audit criteria:**
- **Warning:** localStorage reads without try/catch (throws if storage is full, disabled, or corrupted JSON)
- **Warning:** Missing versioned key prefix (`metronow.atlas.*.v1`)
- **Info:** Large objects stored without size check

## 9. XSS Prevention

The codebase uses `escapeHtml()` for all user-controlled strings:

```javascript
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
}
```

**Blocker audit:** Search every `innerHTML` assignment. Verify all interpolated values pass through `escapeHtml()`. Known safe patterns: `fmt.num()`, `fmt.time()`, `fmt.bytes()` (return strings from numbers). Unsafe: any value from `w.name`, `tags.*`, `state.discuss`, user-entered text.

## 10. tweaks-panel.jsx (React Component)

This is the only React code. It ships reusable form controls (`TweakSlider`, `TweakRadio`, `TweakColor`, `TweakToggle`, etc.) and the host-protocol bridge (`useTweaks` hook).

**Audit criteria:**
- Standard React rules apply here only (hooks rules, key props, dependency arrays)
- **Warning:** `window.addEventListener` in pointer handlers without cleanup
- Components are exported to `window` via `Object.assign(window, { ... })`, which is intentional for non-module usage

## 11. atlas-extras.js Patterns

- Injects its own `<style>` element at runtime
- Redefines `$()` and `escapeHtml()` locally (not shared with atlas.js)
- Patches `window.fetch` for rate-limiting API GETs (coalescing, micro-cache)
- Uses `MutationObserver` to re-run enhancers on DOM changes

**Audit criteria:**
- **Warning:** Fetch patch affects ALL GET requests to `/api/`, not just specific endpoints
- **Warning:** Cache TTL (`CACHE_MS = 1500`) may serve stale data after rapid writes
- **Info:** Observer fires on every DOM mutation; consider debouncing `tick()`
