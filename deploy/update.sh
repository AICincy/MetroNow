#!/usr/bin/env bash
# Pull the latest code and rebuild + restart the stack in place.
# Run from any working directory; resolves paths relative to this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$APP_DIR"
git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git pull --ff-only origin "$BRANCH"

cd "$SCRIPT_DIR"
docker compose pull --ignore-buildable
docker compose up -d --build
docker image prune -f

echo
echo "Update complete. Tail logs with: docker compose logs -f"
