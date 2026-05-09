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


