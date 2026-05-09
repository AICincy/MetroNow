# MetroNow `metronow-*` skills remediation — 2026-05-09

Living journal of fixes applied today against the audit at
`docs/metro-skills-audit-2026-05-09.md`. Each entry is appended as the
fix lands; failures and dead-ends are captured under "Learnings".

**Branch:** `claude/audit-metro-skills-mB9FB` · **PR:** [#21](https://github.com/AICincy/metronow/pull/21)

**Sequencing (chosen with operator):**

1. Mechanical fixes (file-by-file, low-risk).
2. Design-call fixes (console tokenization, `.fx-result` token migration,
   overlay focus-trap).
3. Skill-text drift fixes (separate commit per operator direction).

**Operator decisions captured up-front:**

- Console palette: keep dark in both themes. Tokenize via dedicated
  `--console-*` tokens, identical values in `:root` and
  `[data-theme="dark"]`.
- Skill-text drift: fix in a separate commit on this branch (not a
  separate PR).

---

## Log

### Entry 1 — Skill-text drift fixes (priority bump)

**Why first:** Gemini-code-assist bot opened 5 review comments on PR #21
within minutes of the draft being pushed. Every comment flagged the same
drift items the audit already documented (FastAPI vs Express, missing
`tweaks-panel.jsx`, Python 3.11 → 3.12, redundant H1s in references,
`uvicorn` → `node web/server.js`). Fixing skill text first silences the
bot's noise on the rest of the PR and addresses the operator's twice-
confirmed "yes."

**Files changed:**

- `.claude/skills/metronow-code-review/SKILL.md` — description/architecture
  rewritten to Express.js + Python `osm` CLI; line counts corrected;
  `tweaks-panel.jsx` and `docker-compose.yml` references removed;
  routing list reduced to actual extensions.
- `.claude/skills/metronow-code-review/references/dockerfile.md` — full
  rewrite. Now describes the actual three-stage build (python-deps +
  node-deps + final python:3.12-slim with NodeSource Node 20). All
  `uvicorn` examples replaced with `node web/server.js`; Python 3.11
  bumped to 3.12; the inline frontend-port snippet now points at the
  real `web/public/js/atlas.js` path; `.dockerignore` template updated
  to match the repo's actual ignore set; docker-compose section reframed
  as "if added later, audit it for…"
- `.claude/skills/metronow-code-review/references/css.md` — redundant
  `# CSS Audit Standards` H1 dropped per Gemini's explicit suggestion;
  architecture section now lists the two real CSS sources
  (`index.html` `<style>` + `atlas-supplement.css`); `tweaks-panel.jsx`
  and runtime `<style>` injection claims removed; print-styles
  paragraph corrected to point at the inline `<style>` block.
- `.claude/skills/metronow-code-review/references/html.md` — redundant
  H1 dropped; HTML-variants list (`MetroNow_Atlas__bundle_src_.html`,
  etc.) replaced with the actual `web/public/index.html` shipping
  file; non-shipping `docs/*.html` reports noted but de-emphasized;
  inline `<script>` line counts corrected (1639 → 2072, 495 → 132).
- `.claude/skills/metronow-code-review/references/javascript.md` —
  redundant H1 dropped; architecture section now lists only the two
  real JS files with correct line counts; tweaks-panel.jsx React
  section (§10) deleted; atlas-extras.js section (§11) rewritten to
  match the actual 132-line file (no `MutationObserver`, no
  `window.fetch` patching, no runtime `<style>` injection — instead
  documents `loadDefaults()`, `localStorage` with the missing
  `try/catch` on the writer, accent/density/weight appliers, theme
  toggle).
- `.claude/skills/metronow-dockerfile-review/SKILL.md` — description
  + body rewritten to Express+Python hybrid; Python 3.11 → 3.12;
  uvicorn → node web/server.js; healthcheck endpoint /health →
  /api/zones with the actual node one-liner; `.dockerignore`
  template updated; docker-compose section reframed.
- `.claude/skills/metronow-css-review/SKILL.md` — description corrected;
  architecture section now lists the two real CSS sources; runtime
  injection + tweaks-panel.jsx claims removed; print-styles paragraph
  corrected.
- `.claude/skills/metronow-html-review/SKILL.md` — description and
  variants list updated to the real `web/public/index.html`; inline
  `<script>` line counts corrected.
- `.claude/skills/metronow-javascript-review/SKILL.md` — description
  drops "JSX" mention; compatibility line drops React; architecture
  section lists only two real files with correct line counts;
  tweaks-panel.jsx React section deleted; atlas-extras.js section
  rewritten.

**Successes:**
- Skill descriptions visible in Claude's skill registry now reflect
  reality (verified by the auto-refreshed available-skills list).
- Gemini's specific suggestions (5 review comments) are all addressed
  in this commit.

**Failures / dead-ends:** None.

**Learned:**
- The `.skill` zip format is just a renamed ZIP; `unzip -o` is enough
  to install one into `.claude/skills/` and have the harness pick it
  up at the next prompt.
- Skill descriptions auto-update in the available-skills system
  reminder after the file changes — no reload needed.

---

### Entry 2 — Dockerfile hardening (commit `3c6e0f9`)

**Resolves:** audit Blocker #1 (no non-root USER), Warning (redundant
`COPY src/ src/` in final stage).

**Changes:**
- Added system `metronow` user (uid 1000) with home at /home/metronow.
- All app-level COPY ops now use `--chown=metronow:metronow`.
- Pre-create `/home/metronow/.config/osm` and set HOME / XDG_CONFIG_HOME
  so the `osm` CLI's credential path resolves correctly under the
  non-root user.
- Drop the duplicate `COPY src/ src/` from the final stage. The
  python-deps stage already installs the `osm` package into
  `/usr/local/lib/python3.12/site-packages` — the runtime image does
  not need a second copy of the source tree.
- `.dockerignore` extended with `.claude/`, `.pytest_cache`,
  `.ruff_cache`, `*.egg-info`, `.vscode`, `.idea`, `docs/`,
  `osm-audit-*/`, `tests/`, `.env.*`, `.github`, `.gitignore`,
  `.dockerignore`. Removes ~50% of the typical local build context
  and keeps the new `.claude/` skill packs out of images.

**Successes:** Image now meets non-root-user requirement.
**Failures:** None.

---

### Entry 3 — atlas-supplement.css token migration (commit `7215ee4`)

**Resolves:** audit Blocker #3 (`.fx-result` tokenization), 3 Warnings
(undefined `--border` token, mismatched `--brand` fallbacks).

**Changes:**
- `var(--border)` → `var(--line)` at 12 call sites (token was never
  defined; properties were silently resolving to `currentColor`).
- `.fx-result.ok` and `.fx-result.err` now use `var(--ok-bg)` /
  `var(--ok)` / `var(--err-bg)` / `var(--err)`. Standalone
  `[data-theme="dark"] .fx-result` overrides removed because the
  underlying tokens already flip in the dark theme block.
- Drop literal-hex fallbacks on `var(--brand, #d35400)` and
  `var(--brand, #2b6cb0)` — both were rust/steel-blue, neither
  matched the actual `--brand: #fa6800`.

**Successes:** Dark-mode parity achieved automatically through the
existing token system. No theme-specific JS or CSS overrides needed.

**Failures:** First Edit batch silently no-op'd (replace_all reported
success but file was unchanged). Re-running the same Edit calls
landed cleanly. Cause unclear; may be a transient harness state issue.

**Learned:** Always verify Edit success with a follow-up `grep -nc`
when working at scale — relying solely on the success message is not
enough.

---

### Entry 4 — Console palette tokenization (commit `059ec9f`)

**Resolves:** audit Blocker #2 (~25 hardcoded hex literals across the
console section in `index.html` + `atlas-supplement.css`).

**Operator decision applied:** Keep console dark in both themes.
Tokenize without theme overrides so the dark "terminal" surface is
preserved by design intent rather than reproduced by accident.

**Changes:**
- 17 new `--console-*` tokens defined in `:root` of `index.html`,
  semantically grouped (bg, fg, line, tag-*, line-* variants, dot-err).
- ~30 component rules across both files now reference the tokens
  instead of literal hex (`.console-panel`, `.console-head`, dots,
  body, scrollbar, `.cl-*` row classes, `.console-line.*`,
  `.ck-dot.*`).
- rgba shadow halos on `.ck-dot` keyframes kept as literal rgba
  (opacity-only variants of dot color, canonical shadow pattern).

**Successes:** All hardcoded console hex removed from component rules.
**Failures:** None.

---

### Entry 5 — HTML semantic + ARIA + SRI (commit `d406557`)

**Resolves:** 7 audit Warnings — semantic markup, screen-reader
semantics, and CDN integrity.

**Changes:**
1. `brand-mark` `<span>` → `<h1>` (page now has top-level heading).
   Added `margin: 0;` to `.brand-mark` CSS so default h1 margins don't
   break the flex baseline alignment of `.brand`.
2. Breadcrumb `<span class="crumb">` → `<nav aria-label="Breadcrumb">`
   wrapping `<ol><li>...</li></ol>` with `aria-current="page"` on the
   final crumb. CSS adapted: flex moved from `.crumb` to `.crumb ol`,
   list-style/margin/padding reset on the `<ol>`. No JS change — atlas.js
   still hits `#crumbZone` via `textContent` which works on `<li>`.
3. Map: `<div id="map">` gains `role="application"` and
   `aria-label="Hamilton County zone map with TIGER defect overlay"`.
4. Search input: `type="text"` → `type="search"` plus
   `aria-label="Search streets and way IDs"`.
5. Legend container gains `aria-live="polite" aria-atomic="false"`.
6. All seven overlay panels (`panel-results`, `panel-fix`,
   `panel-investigations`, `panel-history`, `panel-discuss`,
   `panel-formality`, `panel-auth`) gain `role="dialog"`,
   `aria-modal="true"`, and `aria-labelledby="<panel-id>-title"`. Each
   `<h2 class="overlay-title">` gets a matching `id`.
7. SRI `integrity="sha384-…"` + `crossorigin="anonymous"` added to all
   six external CDN resources (Leaflet 1.9.4 css+js, leaflet.markercluster
   1.5.3 css+css+js, esri-leaflet 3.0.14 js). Hashes computed locally
   via `curl … | openssl dgst -sha384 -binary | openssl base64 -A`.

**Successes:** Hashes computed on the first try (curl + openssl available
in the sandbox). Page now satisfies all seven ARIA Warnings cited in the
audit (focus-trap deferred to next entry).

**Failures:** None.

---

### Entry 6 — JS panel focus-trap + esc symmetry (commit `4961365`)

**Resolves:** the deferred focus-trap Warning, three remaining JS
Warnings.

**Changes:**

`atlas.js` — focus trap and dialog behavior:
- `openPanel()` captures `document.activeElement` and focuses the first
  focusable inside the opened panel.
- A document-level `keydown` handler cycles Tab / Shift+Tab within the
  trapped panel and closes on Escape.
- `closeAllPanels()` restores focus to the original opener so keyboard
  users land back on the dock button.
- `focusableWithin()` filters by `offsetParent` visibility so hidden
  close-buttons inside other (non-shown) panels don't pollute the trap.

`atlas.js` — dock active-tab semantics:
- `openPanel`/`closeAllPanels` now toggle `aria-current="page"` on the
  active dock button alongside `aria-pressed`. HTML initial state for
  the "Map" dock button gets `aria-current="page"` so first-paint state
  is correct.

`atlas.js` — esc symmetry (audit Warning, lines 1521/1525/1527):
- Server-returned values now run through `esc()` before innerHTML
  interpolation: `result.fixes_applied` (twice) and `id` (changeset id).
- href URL component uses `encodeURIComponent(id)` since URL escaping
  rules differ from HTML escaping.

`atlas.js` — listener consistency (line 621):
- `el.onclick = ...` → `el.addEventListener("click", …)`. The line
  three above already used `addEventListener`; the legend wire-up
  was the only stale spot in the file.

`atlas-extras.js` — localStorage hardening:
- `save()` wraps `localStorage.setItem(...)` in try/catch.
  Quota-exceeded, private-mode, and serialization failures now silently
  skip instead of throwing into the user's interaction.

**Successes:** All JS Warnings closed in one focused commit.
**Failures:** None.

---

## Audit roll-up — end of 2026-05-09

| Skill                     | Open Blockers | Open Warnings | Open Info |
|---------------------------|--------------:|--------------:|----------:|
| metronow-code-review      |             0 |             0 |         0 |
| metronow-dockerfile-review|             0 |             0 |         0 (skill-cite items) |
| metronow-css-review       |             0 |             0 |         0 |
| metronow-html-review      |             0 |             0 |         0 |
| metronow-javascript-review|             0 |             0 |         0 |

All 3 Blockers + 18 Warnings from the morning audit are resolved on
this branch. The 14 Info items in the original audit were observations
(no remediation required).

**What ships in PR #21 (commits, in order):**

1. `c1881e6` — initial: skills installed + audit report
2. `48a61bb` — skill-text drift fixed (FastAPI → Express, line counts,
   tweaks-panel.jsx removed, redundant H1s dropped, Python 3.11→3.12)
3. `3c6e0f9` — Dockerfile hardening (non-root USER, --chown, dropped
   redundant src/ COPY, .dockerignore expanded)
4. `7215ee4` — CSS token migration (`--border`→`--line`, `.fx-result`
   tokenized, mismatched `--brand` fallbacks dropped)
5. `059ec9f` — console palette tokenization (16 new `--console-*`
   tokens, ~30 component refs migrated)
6. `d406557` — HTML accessibility hardening (h1 / breadcrumb /
   map ARIA / search input / legend aria-live / 7 overlay
   role=dialog / SRI hashes for all 6 CDN resources)
7. `4961365` — JS panel focus-trap, esc() symmetry, listener
   consistency, localStorage try/catch

**Followups (not in scope for today):**

- The original audit's "skills assume FastAPI" drift is fully
  addressed in commit 2; if any future skill packs land, run
  through them with the same pattern.
- The audit's broader contrast-ratio caveats on `--ink-faint`,
  `--ink-mute`, `--brand` (CSS skill §6) are reminders to keep
  body text off those tokens — not active findings to remediate
  today, since they are correctly used as decorative-only colors
  per the existing markup.


