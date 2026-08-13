# 🌐 Scaling to Multiple Servers & Company Fleet Guide

This guide explains how to scale and replicate this AI-driven development environment across **multiple servers, teams, and departments** in your company.

---

## 🏛️ Fleet Architecture Topologies

Depending on your company's workflow, choose one of the three proven scaling patterns:

```
                              NAMECHEAP DNS
                                    │
           ┌────────────────────────┼────────────────────────┐
           │ *.dev-server           │ *.gpu                  │ *.sarah.dev
           ▼                        ▼                        ▼
    ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
    │  DEV SERVER  │         │   GPU BOX    │         │ SARAH'S NODE │
    │   (Node 1)   │         │ (ML / Sar)   │         │  (Frontend)  │
    │              │         │              │         │              │
    │ Caddy        │         │ Caddy        │         │ Caddy        │
    │ OpenCode     │         │ OpenCode     │         │ OpenCode     │
    │ AI-Ops       │         │ AI-Ops       │         │ AI-Ops       │
    │ devctl       │         │ devctl       │         │ devctl       │
    └──────────────┘         └──────────────┘         └──────────────┘
```

### Pattern 1: Per-Developer / Per-Team Autonomous Devboxes (Recommended)
Every developer or team gets their own persistent VPS (e.g. Hetzner 4 vCPU / 8GB RAM, AWS, DigitalOcean, or bare metal).
- **Domain Scheme**:
  - `*.dev-server.datakrib.com` $\rightarrow$ General Dev
  - `*.john.dev.datakrib.com` $\rightarrow$ John's Devbox
  - `*.sarah.dev.datakrib.com` $\rightarrow$ Sarah's Devbox
- **Benefits**:
  - Complete isolation: Developer A crashing their Docker container or running heavy tests does not impact Developer B.
  - Zero port collisions: Both engineers can expose a service named `api` without conflict (`api.john.dev...` vs `api.sarah.dev...`).

---

### Pattern 2: Workload-Segregated Fleet
Split servers by compute capabilities:
1. **General Web/API Nodes** (`*.dev-server.datakrib.com`): Lightweight Docker apps, Next.js, Node, Go, Python APIs.
2. **GPU / AI Compute Workstations** (`*.gpu.datakrib.com`): High-VRAM GPU servers running local LLMs (vLLM, Ollama), SAR radar pipelines, or ML training.
3. **Staging / QA Cluster** (`*.staging.datakrib.com`): Pre-release integration environments tested automatically by Playwright.

---

### Pattern 3: Private WireGuard / Tailscale Mesh Overlay
For enterprise internal-only fleets where you do not want services reachable over public internet:
1. Connect all servers to a private **Tailscale / WireGuard** mesh.
2. Caddy binds to the Tailscale interface (`100.x.y.z`).
3. Only company employees with active VPN/Tailscale access can reach `https://*.dev-server.datakrib.com`.

---

## 📡 Namecheap DNS Wildcard Configuration for Multiple Servers

In Namecheap (or your DNS provider), add an `A Record` for each server's wildcard:

| Type | Host | Value | TTL |
| :--- | :--- | :--- | :--- |
| **A Record** | `*.dev-server` | `SERVER_1_IP` | Automatic |
| **A Record** | `*.node2` | `SERVER_2_IP` | Automatic |
| **A Record** | `*.gpu` | `GPU_SERVER_IP` | Automatic |
| **A Record** | `*.staging` | `STAGING_SERVER_IP` | Automatic |
| **A Record** | `*.john.dev` | `JOHN_SERVER_IP` | Automatic |

Each wildcard A-record directs subdomain traffic directly to that specific server, where Caddy and `devctl` route it to internal Docker containers on `dev-net`.

---

## ⚡ 1-Command Automated Fleet Provisioning (Ansible)

To provision **1 to 100 servers** in parallel across your company:

### Step 1: Configure Fleet Inventory
Edit [`infra/ansible/inventory.ini.example`](file:///c:/Users/Admin/Documents/antigravity/happy-galileo/infra/ansible/inventory.ini.example):
```ini
[dev_fleet]
node1       ansible_host=198.51.100.10  base_domain=dev-server.datakrib.com
gpu-box     ansible_host=198.51.100.20  base_domain=gpu.datakrib.com
dev-sarah   ansible_host=198.51.100.30  base_domain=sarah.dev.datakrib.com
```

### Step 2: Run the Fleet Playbook
```bash
ansible-playbook -i infra/ansible/inventory.ini infra/ansible/playbook.yml
```

Ansible will concurrently:
1. Install Docker, Caddy, Fail2ban, UFW, Node/Playwright, OpenCode on every server.
2. Lock down firewalls (UFW 22, 80, 443).
3. Create the `dev-net` internal Docker network on all nodes.
4. Configure domain scopes (`BASE_DOMAIN`) dynamically.
5. Deploy Caddy dynamic reverse proxy and AI-Ops monitoring daemons on each node.

---

## 🔔 Centralizing AI-Ops Incidents Across the Fleet

In a company setting, you can forward AI-Ops Level 3 incidents to your company Slack, Discord, or webhook:

Set in `.env` or server environment:
```bash
INCIDENT_WEBHOOK_URL="https://discord.com/api/webhooks/XXXXX"
# or
INCIDENT_SLACK_WEBHOOK="https://hooks.slack.com/services/XXXXX"
```

When AI-Ops on **any** node detects an HTTP 500 regression, it:
1. Builds the local incident dossier in `.devctl/incidents/`.
2. Emits the incident to the central webhook with server ID, stack trace, and failing URL.
3. OpenCode on that specific server claims and resolves the incident.

---

## 🔒 Enterprise Best Practices

1. **Role-Based Developer Isolation**:
   - Give developers non-root sudoer users for `tmux` and `devctl`.
   - Never share root passwords; use SSH public keys in `~/.ssh/authorized_keys`.
2. **Central Image Registry**:
   - Use your company container registry (GitHub Packages `ghcr.io` or Docker Hub) so images built on dev nodes can deploy seamlessly to staging/prod.
3. **Automated Nightly Cleanup**:
   - Add a cron job to prune dangling Docker images and temporary branch routes older than 7 days:
   ```bash
   0 3 * * * docker system prune -af --volumes --filter "until=168h"
   ```
