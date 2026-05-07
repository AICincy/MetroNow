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

WORKDIR /app

COPY --from=python-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-deps /usr/local/bin/osm /usr/local/bin/osm
COPY --from=node-deps /app/web/node_modules web/node_modules

COPY src/ src/
COPY pyproject.toml .
COPY web/ web/

RUN mkdir -p /root/.config/osm

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/api/zones',r=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"

CMD ["node", "web/server.js"]
