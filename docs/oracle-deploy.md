# Oracle Cloud Always Free deployment

Run MetroNow on a free-forever Oracle Cloud Ampere A1 VM (4 OCPU /
24 GB RAM / 200 GB block storage). Total recurring cost: **$0**, as
long as you stay inside Always Free shape limits.

The repo ships everything needed:

- `Dockerfile` — multi-stage build (Python 3.12 + Node 20 + the `osm` CLI)
- `deploy/docker-compose.yml` — app + Caddy reverse proxy + persistent volumes
- `deploy/Caddyfile` — auto-HTTPS via Let's Encrypt
- `deploy/.env.example` — the two values you have to fill in
- `deploy/bootstrap.sh` — first-time VM setup (Docker, ufw, repo clone)
- `deploy/update.sh` — pull, rebuild, restart

## What persists across rebuilds

Mounted on the `osm_config` named Docker volume → `/root/.config/osm`:

- `credentials.json` — OAuth client credentials
- `token.json` — OAuth access + refresh token
- `cagis_cache/` — CAGIS centerline cache (90-day TTL)
- `history_cache/` — OSM way-history cache (7-day TTL)

**Not yet persisted (known limitation):** `edit-history.json` and
`osm-audit-{zone}/` directories live under `/app` and are reset on
container rebuild. Filed as a follow-up; relocating them under
`/root/.config/osm/` is a one-line Python change plus a server.js
path update.

The `caddy_data` volume holds the issued TLS certificate and ACME
account key — **do not delete it casually** or you'll burn Let's
Encrypt rate-limit budget (5 duplicate certs per registered domain
per week).

## Step-by-step (one-time setup)

These are the **manual** steps — everything else is scripted.

### 1. Create the OCI account

Go to <https://signup.cloud.oracle.com/> and sign up. You will need:

- A **credit card** for identity verification (charged $0; Oracle
  authorizes a small amount and refunds it). Set a $0 spending
  limit in Billing > Cost Management afterward to make sure you
  never get charged.
- **Phone number** for SMS verification.
- A **home region** — pick one with Ampere A1 capacity (`us-ashburn-1`
  and `us-phoenix-1` are usually best in the US). This is permanent.

### 2. Provision the VM

In the OCI Console: **Compute > Instances > Create instance**.

| Field | Value |
|---|---|
| Image | Canonical Ubuntu 22.04 (Aarch64) |
| Shape | `VM.Standard.A1.Flex`, 4 OCPU, 24 GB memory |
| Network | Use the default VCN; assign a **public IPv4** |
| SSH keys | Paste your `~/.ssh/id_ed25519.pub` |
| Boot volume | 100 GB (free) |

If "Out of capacity" appears (common for A1), retry every ~30 min
or pick a less popular region. There's no way around this — Oracle
oversold A1 capacity in 2022-2023.

Once it boots, copy the **public IP** from the instance detail page.

### 3. Open ports 80/443 in the VCN security list

**This is the single biggest gotcha.** Oracle blocks ingress on 80
and 443 by default at the network layer. `ufw` on the VM is not
enough.

In the OCI Console:

1. **Networking > Virtual Cloud Networks** → click your VCN
2. Click the public subnet → click the default **Security List**
3. **Add Ingress Rules**:

   | Source CIDR | Protocol | Dest Port |
   |---|---|---|
   | `0.0.0.0/0` | TCP | 80 |
   | `0.0.0.0/0` | TCP | 443 |
   | `0.0.0.0/0` | UDP | 443 |

The UDP/443 rule is for HTTP/3 (QUIC). Caddy serves it automatically.

### 4. Point your domain at the VM

At your DNS provider, create an `A` record from your chosen
hostname (e.g. `metronow.example.org`) to the VM's public IP.

Wait until it resolves before continuing:

```sh
dig +short metronow.example.org
```

Should print the VM IP. If it doesn't, give DNS more time —
Caddy will fail to issue a cert if the hostname doesn't yet
resolve.

### 5. SSH in and run bootstrap

```sh
ssh ubuntu@<vm-public-ip>
curl -fsSL https://raw.githubusercontent.com/AICincy/MetroNow/main/deploy/bootstrap.sh | bash
exit            # log out so docker group membership applies
ssh ubuntu@<vm-public-ip>
```

### 6. Configure and start

```sh
cd /opt/metronow
nano deploy/.env       # fill in DOMAIN and ACME_EMAIL
cd deploy
docker compose up -d --build
docker compose logs -f caddy   # watch the first cert issue
```

First cert issue takes ~30s. When you see
`certificate obtained successfully`, hit `https://YOUR.DOMAIN`
in a browser.

## Day-to-day

```sh
# pull latest, rebuild, restart
/opt/metronow/deploy/update.sh

# tail logs
cd /opt/metronow/deploy && docker compose logs -f

# restart just the app (not Caddy)
docker compose restart app

# inspect the persisted config volume
docker run --rm -v metronow_osm_config:/c alpine ls -la /c
```

## Out-of-band OAuth bootstrap

The OSM OAuth flow uses the OOB redirect (`urn:ietf:wg:oauth:2.0:oob`),
so there's no callback URL to configure on osm.org's side. To seed
the token on the server:

```sh
# inside the running container
docker compose exec app python -m osm auth login
```

Follow the printed URL, paste the verification code back, and the
token lands in the persistent volume at
`/root/.config/osm/token.json`.

## Resources used (Always Free check)

| Resource | Used | Free limit |
|---|---|---|
| Ampere A1 OCPU | 4 | 4 |
| Ampere A1 RAM | 24 GB | 24 GB |
| Block storage | ~100 GB | 200 GB |
| Outbound transfer | varies | 10 TB/mo |

If you ever need a second VM (staging), you have **0 OCPU left**
under Always Free — A1 is one shape pool shared across the tenancy.
