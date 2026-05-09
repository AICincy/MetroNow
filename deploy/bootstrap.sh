#!/usr/bin/env bash
# One-time setup for a fresh Oracle Cloud Always Free Ubuntu 22.04 VM
# (Ampere A1, 4 OCPU / 24 GB). Run as the default `ubuntu` user with sudo.
#
#   ssh ubuntu@<vm-public-ip>
#   curl -fsSL https://raw.githubusercontent.com/aicincy/metronow/claude/setup-netlify-config-tT5fD/deploy/bootstrap.sh | bash
#
# Idempotent: safe to re-run.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/aicincy/metronow.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/metronow}"

log() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
	echo "Run as a non-root user with sudo, not as root." >&2
	exit 1
fi

log "Updating apt and installing prerequisites"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
	ca-certificates curl gnupg git ufw

log "Installing Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
	sudo install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
		| sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
	sudo chmod a+r /etc/apt/keyrings/docker.gpg
	echo \
		"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
		| sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
	sudo apt-get update -y
	sudo apt-get install -y \
		docker-ce docker-ce-cli containerd.io \
		docker-buildx-plugin docker-compose-plugin
fi
sudo usermod -aG docker "$USER"

log "Configuring host firewall (ufw)"
# Oracle's VCN security list is the gating firewall — ufw is belt-and-suspenders.
# Open 80/443 in the OCI Console too, or this is wasted.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw --force enable

log "Cloning repo to ${APP_DIR}"
if [[ ! -d "$APP_DIR/.git" ]]; then
	sudo mkdir -p "$APP_DIR"
	sudo chown "$USER:$USER" "$APP_DIR"
	git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
	git -C "$APP_DIR" fetch origin "$BRANCH"
	git -C "$APP_DIR" checkout "$BRANCH"
	git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
fi

log "Seeding deploy/.env (you must edit this before first start)"
if [[ ! -f "$APP_DIR/deploy/.env" ]]; then
	cp "$APP_DIR/deploy/.env.example" "$APP_DIR/deploy/.env"
	echo "Edit $APP_DIR/deploy/.env to set DOMAIN and ACME_EMAIL."
fi

cat <<EOF

==============================================================
Bootstrap complete. Next steps (manual):

  1. Log out and back in so docker group membership applies:
       exit
       ssh ubuntu@<vm-public-ip>

  2. Open ports 80/443 in the OCI Console (VCN > Security List).
     This is REQUIRED — ufw alone is not enough on Oracle Cloud.

  3. Point your domain's A record at this VM's public IP, then
     wait until \`dig +short YOUR.DOMAIN\` returns it.

  4. Edit deploy/.env:
       nano $APP_DIR/deploy/.env

  5. Start the stack:
       cd $APP_DIR/deploy
       docker compose up -d --build

  6. Tail logs to watch the first cert issue:
       docker compose logs -f caddy

==============================================================
EOF
