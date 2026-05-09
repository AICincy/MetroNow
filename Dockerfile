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

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r metronow \
    && useradd -r -g metronow -u 1000 -m -d /home/metronow metronow

WORKDIR /app

COPY --from=python-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-deps /usr/local/bin/osm /usr/local/bin/osm
COPY --from=node-deps --chown=metronow:metronow /app/web/node_modules web/node_modules

COPY --chown=metronow:metronow pyproject.toml .
COPY --chown=metronow:metronow web/ web/

# /app itself must be writable by the metronow user — the Express server
# creates `osm-audit-<zone>/` directories during scans and writes
# `edit-history.json` at PROJECT_ROOT (= /app inside the container).
# Without this chown, those writes would fail with EACCES under USER metronow.
RUN chown metronow:metronow /app \
    && mkdir -p /home/metronow/.config/osm \
    && chown -R metronow:metronow /home/metronow/.config

USER metronow

ENV HOME=/home/metronow
ENV XDG_CONFIG_HOME=/home/metronow/.config

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/health',r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"

CMD ["node", "web/server.js"]
