# ServerGuard Deployment Guide

> **Production deployment commands for Hub + Node setup.**
> The Hub runs the fleet dashboard and telemetry ingest. Nodes run the AI-Ops monitoring daemon and stream telemetry back to the Hub.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [1. Primary Hub Setup](#1-primary-hub-setup)
- [2. Sub-Node Enrollment](#2-sub-node-enrollment)
- [3. Post-Deployment Verification](#3-post-deployment-verification)
- [4. Fleet Management](#4-fleet-management)
- [5. Updating & Redeploying](#5-updating--redeploying)
- [6. Troubleshooting](#6-troubleshooting)
- [Reference](#reference)

---

## Prerequisites

All servers need:

| Requirement | Minimum |
|---|---|
| OS | Ubuntu 22.04+ / Debian 12+ |
| RAM | 2 GB (4 GB recommended) |
| Disk | 20 GB free |
| Network | Outbound HTTPS (443) to Hub |
| Docker | Installed automatically by scripts |
| GitHub PAT | Required on every node (for OpenCode code access) |

---

## 1. Primary Hub Setup

The **Hub** is the central server that runs the Fleet Dashboard, receives telemetry from all nodes, and aggregates incidents.

### Step 1: Clone the repository

```bash
git clone https://github.com/Unlimited-demi/happy-galileo.git /opt/happy-galileo
cd /opt/happy-galileo
```

### Step 2: Create the environment config

```bash
cp infra/.env.example infra/.env
```

Edit `infra/.env`:

```bash
nano infra/.env
```

Set these values:

```env
# Node identity
NODE_NAME=Primary Hub
BASE_DOMAIN=yourcompany.com                    # Your production domain
CADDY_HTTP_PORT=80
CADDY_HTTPS_PORT=443

# Hub has no upstream hub — leave empty
CENTRAL_HUB_URL=

# Fleet authentication key (all nodes must match this)
FLEET_KEY=your-secret-fleet-key-here

# Optional: GitHub token for OpenCode
GITHUB_TOKEN=ghp_your_token_here
```

> **Important:** `CENTRAL_HUB_URL` must be empty on the Hub. This tells the node it IS the hub.

### Step 3: Install dependencies

```bash
# System packages
apt-get update && apt-get install -y \
  git curl wget tmux ufw fail2ban \
  python3 python3-pip python3-venv \
  jq openssh-client ca-certificates gnupg

# Docker (if not already installed)
curl -fsSL https://get.docker.com | sh

# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# OpenCode AI agent
npm install -g @anthropic-ai/opencode
```

### Step 4: Create the Docker network

```bash
docker network create dev-net 2>/dev/null || echo "Network already exists"
```

### Step 5: Install devctl CLI

```bash
cd /opt/happy-galileo

# Create Python venv
python3 -m venv /opt/devctl-venv
/opt/devctl-venv/bin/pip install -r requirements.txt

# Install CLI wrapper
cat > /usr/local/bin/devctl << 'EOF'
#!/bin/bash
exec /opt/devctl-venv/bin/python3 /opt/happy-galileo/devctl/cli.py "$@"
EOF
chmod +x /usr/local/bin/devctl
```

### Step 6: Start the Hub

```bash
cd /opt/happy-galileo/infra

docker compose -f docker-compose.infra.yml --env-file .env up -d --build
```

This starts three containers:

| Container | Port | Purpose |
|---|---|---|
| `caddy` | 80, 443 | Reverse proxy with on-demand TLS |
| `devctl-dashboard` | 8888 (internal) | Fleet status dashboard |
| `ai-ops-daemon` | — | Monitoring & remediation daemon |

### Step 7: Discover local services

```bash
devctl discover --force
```

### Step 8: Configure DNS

Point these records at the Hub server's IP:

```
A    status.yourcompany.com      → <hub-ip>
A    *.status.yourcompany.com    → <hub-ip>
```

The dashboard will be accessible at:

```
https://status.yourcompany.com
```

Caddy handles TLS automatically via Let's Encrypt on-demand certificates.

### Step 9: Record the Hub telemetry URL

Sub-nodes need this URL to send heartbeats:

```
https://status.yourcompany.com/api/telemetry/ingest
```

Save this — you'll use it in node enrollment.

---

## 2. Sub-Node Enrollment

Sub-nodes run the AI-Ops monitoring daemon and stream telemetry back to the Hub. The enrollment script handles everything automatically.

### Quick enrollment (one-liner)

```bash
curl -sSL https://raw.githubusercontent.com/Unlimited-demi/happy-galileo/master/scripts/setup-node.sh | \
  sudo bash -s -- \
    --node-name "node-name" \
    --domain "node-name.yourcompany.com" \
    --hub-url "https://status.yourcompany.com/api/telemetry/ingest" \
    --fleet-key "your-secret-fleet-key-here" \
    --github-token "ghp_your_token_here" \
    --git-name "Your Name" \
    --git-email "you@yourcompany.com"
```

### Enrollment arguments

| Flag | Required | Default | Description |
|---|---|---|---|
| `--node-name` | Yes | `$(hostname -s)` | Unique name for this server (e.g., `vm2`, `mail`, `api`) |
| `--domain` | Yes | — | Base domain for this node (e.g., `vm2.yourcompany.com`) |
| `--hub-url` | Yes | — | Hub telemetry ingest URL |
| `--fleet-key` | No | `default-fleet-key` | Must match Hub's `FLEET_KEY` in `.env` |
| `--github-token` | No | — | GitHub PAT for code access |
| `--git-name` | No | — | Git identity name |
| `--git-email` | No | — | Git identity email |

### What the script does

```
Step 1: Install system packages (git, tmux, ufw, fail2ban, python3, jq)
Step 2: Configure Git identity + GitHub auth
Step 3: Install Docker + Compose (if not present)
Step 4: Clone repository to /opt/happy-galileo
Step 5: Install Node.js 20 + Playwright + OpenCode
Step 6: Create dev-net Docker network
Step 7: Install devctl CLI (Python venv + wrapper)
Step 8: Detect existing proxy (nginx/Caddy/Apache) and resolve port conflicts
Step 9: Harden firewall (UFW) — auto-skipped if mail server detected
Step 10: Build and start Caddy + Dashboard + AI-Ops containers
Step 11: Auto-discover existing Docker containers
Step 12: Send initial heartbeat to Hub
Step 13: Run devctl doctor health check
```

### Enrolling multiple nodes

Run the enrollment command on each server. Example fleet:

```bash
# Mail server (Mailcow)
curl -sSL ... | sudo bash -s -- \
  --node-name "mail" \
  --domain "mail.yourcompany.com" \
  --hub-url "https://status.yourcompany.com/api/telemetry/ingest" \
  --fleet-key "your-secret-fleet-key-here" \
  --github-token "ghp_..."

# API server
curl -sSL ... | sudo bash -s -- \
  --node-name "api" \
  --domain "api.yourcompany.com" \
  --hub-url "https://status.yourcompany.com/api/telemetry/ingest" \
  --fleet-key "your-secret-fleet-key-here" \
  --github-token "ghp_..."

# AI/ML server
curl -sSL ... | sudo bash -s -- \
  --node-name "ml" \
  --domain "ml.yourcompany.com" \
  --hub-url "https://status.yourcompany.com/api/telemetry/ingest" \
  --fleet-key "your-secret-fleet-key-here" \
  --github-token "ghp_..."
```

> **Note:** Node names are normalized automatically (`vm-02` → `vm2`) to prevent duplicates in the dashboard.

---

## 3. Post-Deployment Verification

### On the Hub

```bash
# Check all containers are running
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View fleet status
devctl fleet list

# Check system health
devctl doctor

# Test telemetry endpoint
curl -s https://status.yourcompany.com/api/telemetry/ingest -X POST \
  -H "Content-Type: application/json" \
  -H "X-Fleet-Key: your-secret-fleet-key-here" \
  -d '{"node_name":"test","status":"ONLINE"}'
```

### On each sub-node

```bash
# Check containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Test heartbeat to hub
devctl heartbeat

# Run health check
devctl doctor

# Verify services discovered
devctl list
```

### Dashboard access

Open the fleet dashboard:

```
https://status.yourcompany.com
```

You should see all enrolled nodes with green ONLINE status.

---

## 4. Fleet Management

### List all nodes

```bash
devctl fleet list
```

### Prune stale nodes

```bash
# Remove nodes not seen in 60+ minutes (default)
devctl fleet prune --yes

# Custom age threshold
devctl fleet prune --max-age 30 --yes
```

### View services on a node

```bash
devctl list
```

### View container logs

```bash
devctl logs <service-name> --tail 50
```

### Expose a service publicly

```bash
devctl expose grafana 3000
devctl expose api --domain api.yourcompany.com 8000
```

### Remove public access

```bash
devctl hide grafana
```

---

## 5. Updating & Redeploying

### Update all nodes (recommended workflow)

```bash
# On EACH node:
cd /opt/happy-galileo
git fetch origin && git reset --hard origin/master

cd infra
docker compose -f docker-compose.infra.yml --env-file .env build --no-cache
docker compose -f docker-compose.infra.yml --env-file .env up -d

devctl discover --force
```

### Update Hub only

```bash
cd /opt/happy-galileo
git fetch origin && git reset --hard origin/master

cd infra
docker compose -f docker-compose.infra.yml --env-file .env build --no-cache
docker compose -f docker-compose.infra.yml --env-file .env up -d

devctl discover --force
```

### Redeploy a specific service

```bash
devctl deploy <service-name> --pull
devctl deploy <service-name> --pull --no-cache   # Force full rebuild
```

### Redeploy all services

```bash
devctl deploy all --pull --no-cache
```

### One-liner: pull + rebuild + restart + discover

```bash
cd /opt/happy-galileo && \
  git fetch origin && git reset --hard origin/master && \
  cd infra && \
  docker compose -f docker-compose.infra.yml --env-file .env build --no-cache && \
  docker compose -f docker-compose.infra.yml --env-file .env up -d && \
  devctl discover --force
```

---

## 6. Troubleshooting

### Containers not starting

```bash
# Check compose logs
docker compose -f /opt/happy-galileo/infra/docker-compose.infra.yml logs --tail 50

# Check individual container
docker logs caddy --tail 50
docker logs ai-ops-daemon --tail 50
docker logs devctl-dashboard --tail 50
```

### Node not showing in dashboard

```bash
# On the sub-node, test heartbeat
devctl heartbeat

# Check if hub URL is reachable
curl -s -o /dev/null -w "%{http_code}" https://status.yourcompany.com/api/telemetry/ingest

# Verify fleet key matches
grep FLEET_KEY /opt/happy-galileo/infra/.env
```

### Port conflicts (existing nginx/Caddy on 80/443)

```bash
# Check what's using ports 80/443
ss -tlnp | grep -E ':80|:443'

# The proxy_resolver.sh script handles this automatically.
# To re-run:
bash /opt/happy-galileo/infra/security/proxy_resolver.sh
```

### Mail server ports blocked by UFW

```bash
# The UFW script auto-skips mail servers.
# If it already ran, manually allow mail ports:
ufw allow 25/tcp     # SMTP
ufw allow 587/tcp    # Submission
ufw allow 993/tcp    # IMAPS
ufw allow 143/tcp    # IMAP
ufw allow 110/tcp    # POP3
ufw allow 995/tcp    # POP3S
ufw reload
```

### Duplicate nodes in dashboard

```bash
# Node names are normalized automatically.
# If you still see duplicates, prune:
devctl fleet prune --max-age 5 --yes
```

### Full system health check

```bash
devctl doctor
```

---

## Reference

### Architecture

```
┌──────────────────────────────────────────────────────┐
│                  HUB (Primary Server)                 │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │  Dashboard  │  │  AI-Ops    │  │  Telemetry    │  │
│  │  :8888      │  │  Daemon    │  │  Ingest API   │  │
│  └────────────┘  └────────────┘  └───────────────┘  │
│                    Caddy (TLS)                        │
│              status.yourcompany.com                   │
└──────────────────────────────────────────────────────┘
           ▲              ▲              ▲
           │  heartbeat   │  heartbeat   │  heartbeat
           │  (every 15s) │  (every 15s) │  (every 15s)
     ┌─────┴─────┐  ┌────┴──────┐  ┌───┴─────────┐
     │  Node: mail│  │ Node: api │  │  Node: ml   │
     │  AI-Ops    │  │ AI-Ops    │  │  AI-Ops     │
     │  Caddy     │  │ Caddy     │  │  Caddy      │
     └───────────┘  └───────────┘  └─────────────┘
```

### Container stack (every node)

| Container | Image | Purpose |
|---|---|---|
| `caddy` | `caddy:2-alpine` | Reverse proxy, on-demand TLS |
| `devctl-dashboard` | Built from `Dockerfile.dashboard` | Fleet status web UI (React + Flask) |
| `ai-ops-daemon` | Built from `Dockerfile.ai-ops` | Monitoring, detection, remediation |

### Key paths

| Path | Purpose |
|---|---|
| `/opt/happy-galileo/` | Repository root |
| `/opt/happy-galileo/infra/.env` | Node environment config |
| `/opt/happy-galileo/infra/docker-compose.infra.yml` | Container orchestration |
| `/opt/happy-galileo/scripts/setup-node.sh` | Sub-node enrollment script |
| `/opt/happy-galileo/infra/security/proxy_resolver.sh` | Proxy conflict resolution |
| `/opt/happy-galileo/infra/security/ufw_setup.sh` | Firewall hardening |
| `/usr/local/bin/devctl` | CLI wrapper |
| `~/.devctl/fleet/nodes.json` | Fleet node state (Hub only) |
| `~/.devctl/incidents/` | Incident dossiers |
| `~/.devctl/services.json` | Discovered services registry |

### Environment variables

| Variable | Hub | Sub-Node | Description |
|---|---|---|---|
| `NODE_NAME` | `Primary Hub` | `mail`, `api`, `ml` | Display name in dashboard |
| `BASE_DOMAIN` | `yourcompany.com` | `node.yourcompany.com` | Domain for Caddy TLS |
| `CADDY_HTTP_PORT` | `80` | `8080`+ (auto) | HTTP port |
| `CADDY_HTTPS_PORT` | `443` | `8443` | HTTPS port |
| `CENTRAL_HUB_URL` | *(empty)* | Hub ingest URL | Upstream hub (empty = is hub) |
| `FLEET_KEY` | secret | same secret | Fleet authentication |
| `GITHUB_TOKEN` | PAT | PAT | GitHub access for OpenCode |

### Quick command cheat sheet

```bash
# Fleet
devctl fleet list                        # Show all nodes
devctl fleet prune --yes                 # Remove stale nodes

# Services
devctl list                              # List all services
devctl expose <svc> <port>              # Make service public
devctl hide <svc>                        # Remove public access
devctl logs <svc> --tail 50             # View logs
devctl discover --force                  # Re-scan containers

# Incidents
devctl incident list                     # Open incidents
devctl incident inspect <ID>            # Incident details
devctl dispatch <ID>                     # Send to OpenCode
devctl merge <ID> --deploy              # Merge fix + deploy

# Deploy
devctl deploy all --pull                # Rebuild all
devctl deploy <svc> --pull --no-cache   # Force rebuild one service

# Diagnostics
devctl doctor                            # System health check
devctl heartbeat                         # Test hub connectivity
devctl test <svc>                        # Run Playwright tests
```
