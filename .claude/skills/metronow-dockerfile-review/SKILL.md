---
name: metronow-dockerfile-review
description: "Code review and quality standards for MetroNow Atlas Dockerfile configuration. Use this skill when auditing Dockerfiles, docker-compose files, container configs, or when someone asks \"review my Dockerfile,\" \"is this image secure,\" \"optimize my Docker build,\" or \"check my compose file.\" The runtime is a multi-stage build producing a python:3.12-slim image with Node.js 20 layered in; the Express.js server (web/server.js) listens on port 3000 and shells out to the Python `osm` CLI. Frontend is a single HTML file served by Express. Repo: https://github.com/AICincy/MetroNow.git"
compatibility: Docker 24+, Docker Compose v2, BuildKit, Multi-stage builds
---

# MetroNow Atlas Dockerfile Audit Guide

Instructional reference for agents autonomously auditing and remediating MetroNow Atlas container configuration. The runtime is a multi-stage Docker build that produces a `python:3.12-slim` image with Node.js 20 layered in via NodeSource. The Express.js server (`web/server.js`) listens on port 3000 and shells out to the Python `osm` CLI installed from `pyproject.toml` for TIGER audit scans. The frontend is a single HTML file served by Express from the same origin.

Classify every finding:

- **Blocker** - Must fix before merge
- **Warning** - Should fix, creates tech debt
- **Info** - Suggestion for improvement

## 1. Base Image Selection

**Blocker:** Using `:latest` tag (no version pinning)

**Warning:** Using Alpine for the Python stage. The `osm` package depends on geospatial libraries (Shapely, GDAL via wheels) which often hit native-compilation issues on musl. Prefer `python:3.12-slim` or `python:3.12-slim-bookworm`.

```dockerfile
# Blocker
FROM python:latest

# Warning (geospatial dep issues)
FROM python:3.12-alpine

# Correct for MetroNow backend
FROM python:3.12-slim
```

## 2. Security (All Blockers)

**Non-root user:**
```dockerfile
RUN groupadd -r metronow && useradd -r -g metronow -u 1000 metronow
WORKDIR /app
COPY --chown=metronow:metronow . .
USER metronow
```

**No secrets in image layers:**
```dockerfile
# Blocker: visible in history
ENV OSM_API_TOKEN=secret123

# Correct: runtime injection
# docker run -e OSM_API_TOKEN=xxx metronow-atlas
```

**Minimal attack surface:**
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    libgdal-dev \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*
```

## 3. Build Optimization

**Layer caching:** Copy dependency manifest before app code:
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```

**Multi-stage build:** Production images must not contain build tools. The current `Dockerfile` already uses three stages (`python-deps`, `node-deps`, final `python:3.12-slim`):

```dockerfile
FROM python:3.12-slim AS python-deps
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

FROM node:20-slim AS node-deps
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --production

FROM python:3.12-slim
# … add a non-root metronow user, layer Node 20 from NodeSource …
WORKDIR /app
COPY --from=python-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-deps /usr/local/bin/osm /usr/local/bin/osm
COPY --from=node-deps /app/web/node_modules web/node_modules
COPY web/ web/
EXPOSE 3000
CMD ["node", "web/server.js"]
```

Note: The backend runs on port 3000. The frontend hardcodes this in `web/public/js/atlas.js`:
```javascript
const API = (() => {
  const here = new URL(location.href);
  if (["localhost","127.0.0.1"].includes(here.hostname) && here.port === "3000") return "";
  return "http://localhost:3000";
})();
```

## 4. Command Format

**Blocker:** Shell form CMD (PID 1 issues):
```dockerfile
CMD node web/server.js                # Wrong (shell form)
CMD ["node", "web/server.js"]         # Correct (exec form)
```

**Warning:** Multiple RUN layers for one operation. Chain with `&&`.

**Warning:** `ADD` instead of `COPY` (use `ADD` only for tarballs).

## 5. Health Check

**Warning:** Missing `HEALTHCHECK`. The Express server exposes `/health` as a lightweight liveness signal (no subprocess, no disk I/O):
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/health',r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"
```

## 6. .dockerignore

**Warning:** Missing `.dockerignore`. Recommended contents for MetroNow:
```
.git
.github
.gitignore
.env
.env.*
__pycache__
*.pyc
*.egg-info
node_modules
web/node_modules
.pytest_cache
.ruff_cache
.vscode
.idea
.claude/
osm-audit-*/
tests/
docs/
```

## 7. Docker Compose

There is no `docker-compose.yml` in the repository. If one is added later, audit it for:

**Blocker:** Hardcoded secrets or API tokens (use `.env`); missing `restart` policy.

**Warning:** Missing `healthcheck`; dev volumes in production configs; deprecated top-level `version` key.

```yaml
services:
  atlas:
    build:
      context: .
    environment:
      OSM_API_URL: ${OSM_API_URL:-https://overpass-api.de/api}
      CAGIS_DATA_URL: ${CAGIS_DATA_URL}
    ports:
      - "3000:3000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://localhost:3000/api/zones',r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## 8. Frontend Serving

The Express.js backend serves the static frontend from `web/public/` on the same port (3000). The Dockerfile should:
- Copy `web/` into the image so Express can serve `web/public/index.html`, `web/public/js/*`, and `web/public/css/*`.
- Not require any frontend build tools — there is no build step.
- Allow IBM Plex fonts and Leaflet to load from CDN at runtime (not bundled).

## Review Output Format

```
## [File path]

### Blockers
1. [Line X] Description

### Warnings
1. [Line X] Description

### Info
1. [Line X] Suggestion
```

End with summary count and merge-readiness verdict.
