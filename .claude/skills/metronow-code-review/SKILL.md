---
name: metronow-code-review
description: Unified code review and audit standards for the MetroNow Atlas TIGER Audit Console (https://github.com/AICincy/MetroNow.git). Use this skill when auditing any code in the MetroNow project, doing a PR review, checking code quality, validating accessibility, reviewing Docker config, or when someone asks "review this code," "audit the frontend," "check my PR," "what's wrong with this file," or "does this meet our standards." The codebase is vanilla JavaScript (IIFE pattern, no framework), single-file HTML with inline CSS/JS, IBM Plex typography, Leaflet maps, and an Express.js backend on port 3000 that shells out to the Python `osm` CLI. Covers JS, HTML, CSS, and Dockerfile review with severity-classified findings.
---

# MetroNow Atlas Unified Code Audit Guide

Instructional reference for agents autonomously auditing and remediating the MetroNow Atlas codebase. Route to the correct reference file based on file type, then apply the audit criteria.

## Architecture Overview

MetroNow Atlas is a TIGER audit console for OpenStreetMap data in Hamilton County, Ohio. The frontend is a single HTML file (`web/public/index.html`) with inline CSS and two external JS files. No build system, no bundler, no framework. The backend is an Express.js server (`web/server.js`) that shells out to the Python `osm` CLI for audit pipeline work.

Key files:
- `web/public/index.html` (~1815 lines) - Single-page UI shell, inline `<style>` block, links to atlas.js + atlas-extras.js
- `web/public/js/atlas.js` (~2072 lines) - Main app, IIFE, global `state` object, Leaflet map, API calls
- `web/public/js/atlas-extras.js` (~132 lines) - Default-tweak loader, accent/density/weight appliers, theme toggle wiring
- `web/public/css/atlas-supplement.css` (~526 lines) - Components added by atlas.js
- `web/server.js` (~942 lines) - Express.js REST API on port 3000, child-process invocations of the `osm` CLI
- `Dockerfile` - Multi-stage container config (python-deps + node-deps + final python:3.12-slim runtime)

## Routing

Read the appropriate reference file before beginning the audit:

- **`.js` files** (atlas.js, atlas-extras.js, server.js): Read `references/javascript.md`
- **`.html` files**: Read `references/html.md`
- **CSS** (inline `<style>` blocks + `web/public/css/atlas-supplement.css`): Read `references/css.md`
- **`Dockerfile`, `.dockerignore`**: Read `references/dockerfile.md`

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
