---
name: metronow-code-review
description: Unified code review and audit standards for the MetroNow Atlas TIGER Audit Console (https://github.com/AICincy/MetroNow.git). Use this skill when auditing any code in the MetroNow project, doing a PR review, checking code quality, validating accessibility, reviewing Docker config, or when someone asks "review this code," "audit the frontend," "check my PR," "what's wrong with this file," or "does this meet our standards." The codebase is vanilla JavaScript (IIFE pattern, no framework), single-file HTML with inline CSS/JS, IBM Plex typography, Leaflet maps, and a FastAPI backend on port 3000. Covers JS, HTML, CSS, and Dockerfile review with severity-classified findings.
---

# MetroNow Atlas Unified Code Audit Guide

Instructional reference for agents autonomously auditing and remediating the MetroNow Atlas codebase. Route to the correct reference file based on file type, then apply the audit criteria.

## Architecture Overview

MetroNow Atlas is a TIGER audit console for OpenStreetMap data in Hamilton County, Ohio. The frontend is a single HTML file with inline CSS (~800 lines) and JS (~2100 lines across two scripts). No build system, no bundler, no framework (except one JSX utility loaded via Babel CDN).

Key files:
- `atlas.js` (~1639 lines) - Main app, IIFE, global `state` object, Leaflet map, API calls
- `atlas-extras.js` (~495 lines) - Enhancement layer, keyboard shortcuts, fetch patching
- `tweaks-panel.jsx` (~568 lines) - React component for design controls (only React in project)
- `*.html` - Multiple variants (bundle, offline, standalone, audit report, changelog)
- `Dockerfile` / `docker-compose.yml` - Container config for FastAPI backend

## Routing

Read the appropriate reference file before beginning the audit:

- **`.js` files** (atlas.js, atlas-extras.js): Read `references/javascript.md`
- **`.jsx` files** (tweaks-panel.jsx): Read `references/javascript.md` (React section at bottom)
- **`.html` files**: Read `references/html.md`
- **CSS** (inline `<style>` blocks): Read `references/css.md`
- **`Dockerfile`, `docker-compose.yml`, `.dockerignore`**: Read `references/dockerfile.md`

For PRs spanning multiple file types, read all relevant references and produce one combined review.

## Severity Classification

Every finding must be classified:

- **Blocker** - Must fix before merge (bugs, security, accessibility failures, XSS)
- **Warning** - Should fix, creates tech debt (naming, missing aria, performance)
- **Info** - Suggestion (modern patterns, minor polish)

## Cross-Cutting Standards

These apply to ALL file types:

**Security (Blocker):**
- No secrets, API keys, or tokens in source
- All user-provided strings in `innerHTML` must pass through `escapeHtml()`
- No hardcoded URLs to production systems (use `API` base or env vars)

**Consistency (Warning):**
- Use existing patterns (IIFE scope, `$()` helpers, `state` object, `el()` factory)
- Do not introduce new frameworks, build tools, or module systems without discussion
- New CSS must use existing custom properties, not hardcoded values

**General (Warning):**
- No commented-out code blocks
- No TODO/FIXME without an issue tracker link
- No dead code (unreachable branches, unused variables)

## Review Output Format

```
## [File path or section]

### Blockers
1. [Line X] Description of issue
   Fix: suggested correction

### Warnings
1. [Line X] Description of issue
   Fix: suggested correction

### Info
1. [Line X] Suggestion
```

State explicitly if no blockers are found. End with total count and merge-readiness verdict.
