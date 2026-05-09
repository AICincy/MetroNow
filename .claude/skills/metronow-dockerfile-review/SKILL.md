---
name: metronow-dockerfile-review
description: "Code review and quality standards for MetroNow Atlas Dockerfile configuration (0.2% of codebase). Use this skill when auditing Dockerfiles, docker-compose files, container configs, or when someone asks \"review my Dockerfile,\" \"is this image secure,\" \"optimize my Docker build,\" or \"check my compose file.\" The backend is FastAPI on port 3000 with Python geospatial dependencies (GDAL, Shapely). Frontend is a single HTML file. Repo: https://github.com/AICincy/MetroNow.git"
compatibility: Docker 24+, Docker Compose v2, BuildKit, Multi-stage builds
---

# MetroNow Atlas Dockerfile Audit Guide

Instructional reference for agents autonomously auditing and remediating MetroNow Atlas container configuration. The backend is a FastAPI Python service (port 3000) that runs TIGER audit scans against OpenStreetMap data via Overpass API. The frontend is a single HTML file with inline JS/CSS served from the same origin.

Classify every finding:

- **Blocker** - Must fix before merge
- **Warning** - Should fix, creates tech debt
- **Info** - Suggestion for improvement

## 1. Base Image Selection

**Blocker:** Using `:latest` tag (no version pinning)

**Warning:** Using Alpine for the Python backend. MetroNow depends on geospatial libraries (GDAL, Shapely, potentially PROJ). Alpine causes native compilation issues with these. Use `python:3.11-slim` or `python:3.11-slim-bookworm`.

```dockerfile
# Blocker
FROM python:latest

# Warning (geospatial dep issues)
FROM python:3.11-alpine

# Correct for MetroNow backend
FROM python:3.11-slim-bookworm
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

**Multi-stage build:** Production images must not contain build tools:
```dockerfile
FROM python:3.11-slim-bookworm AS builder
WORKDIR /build
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgdal-dev libgeos-dev && \
    pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal32 libgeos-c1v5 curl && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd -r metronow && useradd -r -g metronow metronow
WORKDIR /app
COPY --from=builder /root/.local /home/metronow/.local
COPY --chown=metronow:metronow . .
ENV PATH=/home/metronow/.local/bin:$PATH
USER metronow
EXPOSE 3000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000"]
```

Note: The backend runs on port 3000, not 8000. The frontend hardcodes this:
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
CMD uvicorn app:app --host 0.0.0.0 --port 3000   # Wrong
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000"]  # Correct
```

**Warning:** Multiple RUN layers for one operation. Chain with `&&`.

**Warning:** `ADD` instead of `COPY` (use `ADD` only for tarballs).

## 5. Health Check

**Warning:** Missing `HEALTHCHECK`. The backend exposes `/health`:
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1
```

## 6. .dockerignore

**Warning:** Missing `.dockerignore`. Required contents for MetroNow:
```
.git
.gitignore
.env
.env.*
__pycache__
*.pyc
node_modules
.vscode
.idea
*.md
docs/
.claude/
*.html
!index.html
```

Note: Exclude HTML variants (`MetroNow_Atlas__offline_.html`, etc.) from the build context. Only include the main `index.html` served by FastAPI.

## 7. Docker Compose

**Warning:** Using deprecated `version` key.

```yaml
services:
  atlas:
    build:
      context: .
      target: production
    environment:
      OSM_API_URL: ${OSM_API_URL:-https://overpass-api.de/api}
      CAGIS_DATA_URL: ${CAGIS_DATA_URL}
    ports:
      - "3000:3000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Blocker in Compose:**
- Hardcoded secrets or API tokens (use `.env`)
- Missing `restart` policy

**Warning in Compose:**
- Missing `healthcheck`
- Dev volumes in production configs

## 8. Frontend Serving

The FastAPI backend serves the frontend HTML. The Dockerfile should:
- Copy the main HTML file into the app directory
- Not install Node.js or any frontend build tools (there is no build step)
- Ensure IBM Plex fonts and Leaflet load from CDN at runtime (not bundled)

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
