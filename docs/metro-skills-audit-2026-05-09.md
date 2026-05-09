# MetroNow `metronow-*` skills audit — 2026-05-09

Run summary of the five `metronow-*` review skills against the current
working tree (commit ahead of `9836bb9`). One pass per skill, in skill-pack
order. Severity labels follow each skill's own classification text — not the
subagents' interpretation. Every line reference was personally re-verified
in the source before inclusion.

**Skills exercised (in order):**

1. `metronow-code-review` (orchestrator + cross-cutting)
2. `metronow-dockerfile-review`
3. `metronow-css-review`
4. `metronow-html-review`
5. `metronow-javascript-review`

**Important pre-amble — skill/project drift (verified facts):**

These three discrepancies between the new skills and the current repo are
themselves audit findings; they are surfaced once here and not repeated per
skill:

- The skills describe a **FastAPI** backend on port 3000. The repo's actual
  backend is **Express.js** at `web/server.js` (942 lines). Port 3000 is
  correct. `CMD ["node", "web/server.js"]` in `Dockerfile:48` confirms.
- The skills reference `tweaks-panel.jsx`. **No `.jsx` files exist** in the
  repo (`find . -name "*.jsx"` returns empty). The "React via Babel CDN"
  section of `metronow-javascript-review` is non-applicable here.
- Skill line-count expectations are stale: skill says `atlas.js ~1639`,
  actual is 2072; skill says `atlas-extras.js ~495`, actual is 132. The
  `atlas-extras.js` skill section (§11) describes runtime `<style>`
  injection, `window.fetch` patching, and a `MutationObserver` — none of
  those are present in the actual 132-line file (verified by `grep`).

These are **skill-text issues, not code issues** — the skills should be
amended before the next audit cycle so future runs aren't anchored to a
codebase that no longer exists.

---

## 1 · `metronow-code-review` (cross-cutting)

### Blockers

None verified across cross-cutting standards (no secrets in source, no
hardcoded production URLs, IIFE scope intact).

### Warnings

1. **[skills/metronow-code-review/SKILL.md, all references/*.md]** Skill
   text references a FastAPI architecture that does not match the current
   Express.js backend. Routing rules are still correct (file-extension
   based), but architectural assertions in the skill body will mislead
   future audits.
   *Fix:* Update the unified skill and each reference to say "Express.js
   backend on port 3000, Python `osm` CLI invoked via `child_process`".

### Info

1. The skill's severity-classification taxonomy (Blocker / Warning / Info)
   is internally consistent and was usable as written for this audit.

---

## 2 · `metronow-dockerfile-review`

Target file: `Dockerfile` (48 lines). No `docker-compose.yml` present.

### Blockers

1. **[Dockerfile:31, 41, 48]** No non-root `USER` directive. The container
   runs as root (confirmed by `RUN mkdir -p /root/.config/osm` at line 41).
   Skill §2 lists non-root user as a Blocker.
   *Fix:* Add a `metronow` system user before `WORKDIR /app`, `chown` the
   copied app tree, and end with `USER metronow`. The `osm` config dir
   path will need to follow (`/home/metronow/.config/osm`).

### Warnings

1. **[Dockerfile:33–35]** Final stage copies the python `site-packages`
   tree into the system path *and* then re-`COPY src/ src/` at line 37.
   The first copy already includes the installed `osm` package; the second
   adds a duplicate source tree to the runtime image. Bloats the image
   without operational benefit.
   *Fix:* Drop `COPY src/ src/` from the final stage unless `web/server.js`
   reads it directly (verified — it shells out to the installed `osm` CLI,
   not to `src/`).

2. **[.dockerignore]** Missing entries the skill recommends:
   `.claude/`, `.vscode`, `.idea`, `*.md`, `docs/`, `.env.*` (only `.env`
   is currently listed). The first three matter most given `.claude/` now
   contains the new skill packs and shouldn't ship into images.
   *Fix:* Append the missing patterns.

### Info

1. **[Dockerfile:1, 9, 16]** Multi-stage build, `--no-install-recommends`,
   apt list cleanup, curl/gnupg purge, `EXPOSE 3000`, `HEALTHCHECK` — all
   present and correct. Skill §3, §5 satisfied.
2. **[Dockerfile:46]** Healthcheck hits `/api/zones` rather than the
   skill's suggested `/health`. This is fine — `/api/zones` is the actual
   liveness signal for this app.
3. Skill §1 recommends `python:3.11-slim-bookworm`; repo uses
   `python:3.12-slim`. No version-pin issue (`:latest` not used). Acceptable.

**Verdict:** One Blocker (non-root user), two minor Warnings. Merge
should wait on the `USER` directive.

---

## 3 · `metronow-css-review`

Targets: `web/public/index.html` inline `<style>` (~lines 7–1390),
`web/public/css/atlas-supplement.css` (526 lines). No runtime `<style>`
injection by `atlas-extras.js` (verified — the file contains no
`document.createElement("style")` or `appendChild` of a style node).

### Blockers (per skill §2: hardcoded hex bypassing tokens = Blocker)

1. **[index.html:471, 480, 484, 487, 488, 494, 495, 497, 500, 501, 504,
   506–514, 516]** `.console-panel`, `.console-head`, `.cl-row`, `.cl-tag`,
   `.cl-msg` use ~25 hardcoded hex values (`#0d0f12`, `#cfd2c8`, `#15181c`,
   `#23272e`, `#8a857a`, `#6cb273`, `#6b9bd1`, `#e76055`, `#d4a64a`,
   `#c995d6`, `#e07a3f`, `#fff`, `#2c3038`, `#6b6356`) and no
   `[data-theme]` overrides. Skill §2 explicitly classifies hardcoded hex
   that should reference tokens as a Blocker.
   *Mitigating note (not in skill):* These approximate a "terminal"
   aesthetic that is intentionally dark even in light theme. If the design
   intent is to keep the console dark in both themes, the cleanest
   remediation is to introduce dedicated `--console-bg`, `--console-fg`,
   `--console-tag-*` tokens rather than scatter raw hex.

2. **[atlas-supplement.css:229, 230]** `.fx-result.ok` and `.fx-result.err`
   use `rgba(34,140,72,0.10)` / `#197a3c` / `rgba(190,40,40,0.10)` /
   `#b8251f` instead of `var(--ok)`, `var(--ok-bg)`, `var(--err)`,
   `var(--err-bg)` which are defined in `:root`. Lines 232–233 do supply
   `[data-theme="dark"]` text-color overrides, but the background tints
   are still raw rgba.
   *Fix:* `background: var(--ok-bg); color: var(--ok); border-color: var(--ok);`
   (and the `.err` analogue) in both themes.

### Warnings

1. **[atlas-supplement.css:47, 96, 105, 119, 162, 191, 196, 246, 270,
   334]** `var(--border)` referenced 10 times, but `--border` is **not
   defined** in `:root` (the actual token is `--line`). With no fallback
   the property resolves to its initial value, so borders may render as
   `currentColor` rather than the intended neutral.
   *Fix:* Replace all `var(--border)` with `var(--line)`, or add
   `--border: var(--line);` to `:root`.

2. **[atlas-supplement.css:12]** `.skip-nav` background uses
   `var(--brand, #d35400)`. The fallback `#d35400` (rust) does not match
   the actual `:root --brand: #fa6800`. The fallback only fires when the
   token is absent, but if it ever does, the fallback color is wrong.
   *Fix:* Drop the literal fallback or replace with `#fa6800`.

3. **[atlas-supplement.css:520, 521]** `.rd-run-btn` uses
   `var(--brand, #2b6cb0)` — fallback is steel blue, also wrong.
   *Fix:* Same as #2.

4. **[atlas-supplement.css:71–91]** `.console-line.*` and `.ck-dot.*`
   keyframes use ~10 hardcoded hex/rgba values (`#cfd2c8`, `#88c897`,
   `#e89090`, `#d8b870`, `#6cb273`, `#d35858`, plus rgba shadows). Same
   token-bypass pattern as Blocker #1; downgraded to Warning here only
   because these are status-tint shades not currently represented in the
   token system.
   *Fix:* Add semantic console-status tokens or reuse `--ok` / `--err` /
   `--warn`.

5. **[atlas-supplement.css passim]** 30+ distinct hex literals in this
   file (`grep -oE '#[0-9a-fA-F]{3,6}'` shows 37 occurrences). Skill §6
   contrast analysis can't run cleanly until these are tokenized.

### Info

1. **[index.html ~7–250]** Token system in `:root` is exhaustively defined
   (typography, light theme, dark theme, brand, accent, defect classes,
   status, elevation, radii, layout). When used, it is used correctly.
2. **[atlas-supplement.css:27]** `.sr-only` `!important` is acceptable per
   skill §8 (utility/print exemption family).
3. Leaflet CDN versions are pinned (`leaflet@1.9.4`) — skill §9 satisfied.

**Verdict:** Two Blockers (token bypass in console + `.fx-result`),
five structural Warnings. The undefined `--border` token is the highest-
leverage fix — one find/replace touches ten lines.

---

## 4 · `metronow-html-review`

Target: `web/public/index.html` (1815 lines). Other HTML files
(`docs/*.html`, `web/public/.legacy/index.html`) are non-shipping and
were not audited.

### Blockers

None verified. Document structure is sound: `<!DOCTYPE html>`,
`lang="en"`, charset, viewport meta, Leaflet pinned to `1.9.4`. No new
sections lacking landmark elements.

### Warnings

1. **[index.html:1398]** `<span class="brand-mark">MetroNow…</span>`
   should be `<h1>`. The page has no `<h1>` at all (verified by `grep`).
   Skill §3 explicitly flags this.
   *Fix:* Change `<span class="brand-mark">` to `<h1 class="brand-mark">`.

2. **[index.html:1406–1410]** Breadcrumb is built from generic `<span>`
   elements rather than `<nav aria-label="Breadcrumb"><ol><li>…`. Skill §3.
   *Fix:* Wrap in `<nav aria-label="Breadcrumb">`, convert to `<ol><li>`.

3. **[index.html:1520]** `<div id="map">` has no `role` and no
   `aria-label`. Skill §2 classifies this as a Warning.
   *Fix:* Add `role="application" aria-label="Hamilton County zone map"`
   (or `role="img"` if treated as a static image — `application` is more
   accurate given Leaflet pan/zoom).

4. **[index.html:1526]** Search input is `type="text"` with no `<label>`
   or `aria-label` (a sibling SVG icon doesn't count). Skill §3 lists
   both findings.
   *Fix:* `type="search" aria-label="Search streets and way IDs"`.

5. **[index.html:1551–1575]** Legend `.leg-item` buttons hold the per-
   class defect counts in `.leg-count` spans that are updated by JS.
   The legend container has no `aria-live`. Skill §5.
   *Fix:* Add `aria-live="polite"` to `.legend-float` (or to each
   `.leg-count`).

6. **[index.html:1595, 1610, 1626, 1643, 1657, 1671, 1685]** All seven
   `<div class="overlay-panel hidden">` panels lack `role="dialog"` and
   `aria-modal="true"`. Focus is also not trapped on open (no
   `inert`/focus-trap pattern in `atlas.js`). Skill §8 lists both as
   Warnings.
   *Fix:* Add `role="dialog" aria-modal="true" aria-labelledby="<panel-h2-id>"`
   on each, plus a focus-trap helper in JS when panels open.

7. **[index.html:1809, 1810, 1811]** Leaflet, esri-leaflet, and
   leaflet.markercluster scripts loaded from `unpkg.com` without
   `integrity` (SRI) attributes. Skill §10.
   *Fix:* Add SRI hashes (`integrity="sha384-..." crossorigin="anonymous"`).
   Generate via `curl … | openssl dgst -sha384 -binary | openssl base64 -A`.

### Info

1. **[index.html:1794, 1796, 1798]** All three external `target="_blank"`
   links carry `rel="noopener"` — skill §9 satisfied.
2. **[index.html:1460, 1473, 1783]** `aria-live="polite"` and
   `role="status"` correctly applied to console body, stats grid, and
   toast — partial credit toward skill §5 (legend gap noted above).
3. **[index.html:1698]** `<nav class="dock" role="tablist" aria-label="Dashboard views">`
   — landmark + label both present. Skill §7 active-tab `aria-current`
   recommendation could not be verified statically; check whether
   `atlas.js` adds it on view switch (out of HTML-skill scope).

**Verdict:** No Blockers, seven Warnings. WCAG 2.1 AA gaps cluster around
overlay-dialog semantics and the missing `<h1>`/breadcrumb structure. All
seven Warnings are mechanically fixable in <50 LOC total.

---

## 5 · `metronow-javascript-review`

Targets: `web/public/js/atlas.js` (2072 lines), `web/public/js/atlas-extras.js`
(132 lines). No `.jsx` to review.

### Blockers

None verified.

The XSS-pathway grep across all 41 `innerHTML` assignments in `atlas.js`
showed every user-controlled or OSM-tag field correctly funneled through
`esc()` (see lines 523, 575, 609, 649, 1085, 1142, 1164, 1536, 1657, 1665,
1675, 1678, 1682, 1693, etc., all spot-verified). The two innerHTML sites
that interpolate without `esc()` (lines 1521/1525/1527, see Warning 1) take
*server-returned numeric IDs and counts*, which the skill's §9 explicitly
classifies as "known safe patterns" when they are numeric. Strict
defense-in-depth would still escape them; the skill text does not require it
for blockers.

### Warnings

1. **[atlas.js:1521, 1525, 1527]** `${result.fixes_applied}` (number) and
   `${id}` (changeset id, integer from OSM API) are interpolated into
   `innerHTML` without passing through `esc()`. Per skill §9 these are on
   the "known safe" side because they originate as numbers from the
   server, but every other innerHTML site in the file uses `esc()` even
   for numeric fields — the inconsistency is itself a tech-debt signal.
   *Fix:* Add `esc()` for symmetry with the rest of the codebase, or wrap
   `id` in `Number(id)` before interpolation to make the type contract
   explicit.

2. **[atlas.js:617 vs 621]** Three lines apart, the same render uses both
   `addEventListener("click", …)` (line 617, on `.class-row`) and
   `el.onclick = …` (line 621, on `.leg-item`). Skill §3 conventions
   call for consistent helpers.
   *Fix:* Convert line 621 to `el.addEventListener("click", …)`.

3. **[atlas-extras.js:29]** `localStorage.setItem(key, JSON.stringify(v))`
   without try/catch. Skill §8 classifies this as a Warning (quota /
   disabled-storage failure modes).
   *Fix:* Wrap in try/catch; log on failure but don't throw.

### Info

1. **[atlas.js:48–80]** Global `state` object is well-structured and
   confined to the IIFE scope. No external mutations detected. Skill §2
   satisfied.
2. **[atlas.js:174–193]** `selectZone()` correctly resets `state.results`,
   `state.pendingFixes`, and `state.classFilters` when switching zones.
   Skill §2 reset-on-zone-switch satisfied.
3. **[atlas.js entire file]** No `EventSource` usage found. Skill §7
   (SSE lifecycle) is not applicable to the current code.
4. **[atlas-extras.js:1–132]** The actual file is 132 lines and contains
   only: default-tweak loader, persistence, accent + density + weight
   appliers, and theme toggle wiring. It does **not** patch
   `window.fetch`, does **not** use `MutationObserver`, does **not**
   inject a `<style>` element. Skill §11 describes a different file than
   this one — see pre-amble.

**Verdict:** No Blockers; three Warnings, all minor. The file is in
better shape than the skill description implies.

---

## Roll-up

| Skill                     | Blockers | Warnings | Info |
|---------------------------|---------:|---------:|-----:|
| metronow-code-review      |        0 |        1 |    1 |
| metronow-dockerfile-review|        1 |        2 |    3 |
| metronow-css-review       |        2 |        5 |    3 |
| metronow-html-review      |        0 |        7 |    3 |
| metronow-javascript-review|        0 |        3 |    4 |
| **Total**                 |    **3** |   **18** | **14** |

**REMEDIATION STATUS (2026-05-09 EOD):** all 3 Blockers and all 18
Warnings closed on branch `claude/audit-metro-skills-mB9FB` (PR #21).
See `docs/metro-skills-remediation-2026-05-09.md` for the per-commit
breakdown.

**The three Blockers, ranked by remediation leverage:**

1. `Dockerfile` — add non-root `USER`. Single change, container-security
   gate. Also unblocks any future image-scanning policy.
2. `index.html` console section — tokenize the dark "terminal" palette.
   Largest LOC footprint but mechanical (find/replace + new tokens).
3. `atlas-supplement.css` `.fx-result` rgba/hex → `var(--ok)` / `var(--err)`.
   ~6-line patch.

**The single highest-leverage Warning:** `atlas-supplement.css`
`var(--border)` → `var(--line)` find/replace (10 sites). Cleans up an
undefined-token bug that has been silent because CSS tolerates missing
tokens.

**Skill-text drift to fix before next audit cycle:** FastAPI references,
`tweaks-panel.jsx` references, and the `atlas-extras.js` §11 description
are all out of date. Recommend a separate skill-pack maintenance pass —
do not amend skill text inside this audit pass.

---

*This audit was produced by re-applying each `metronow-*` skill's
criteria to the actual source. Every line reference was confirmed by
`grep` or `sed` against the current working tree before inclusion. No
findings were inferred or extrapolated.*
