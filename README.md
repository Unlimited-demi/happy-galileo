# ⚡ Remote Agentic Dev & AI-Ops Workstation

> A production-grade, self-healing remote development workstation for **OpenCode**, **Docker**, **Caddy**, **Playwright**, and an **Autonomous AI-Ops Agent** running on `*.dev-server.datakrib.com`.

---

## 🏛️ Architecture Overview

```
                         YOU (Phone / Laptop)
                                │
                    SSH / HTTPS │ (Browser)
                                ▼
                 ┌─────────────────────────────┐
                 │        SECURITY EDGE        │
                 │  - UFW (only 22, 80, 443)   │
                 │  - Fail2ban (SSH & Caddy)   │
                 │  - Caddy Reverse Proxy      │
                 │  - Automatic TLS / Wildcard │
                 └──────────────┬──────────────┘
                                │ Docker Network (dev-net)
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
  ┌───────────┐           ┌───────────┐           ┌───────────┐
  │ Frontend  │           │    API    │           │ Services  │
  │  (Node)   │           │ (Python)  │           │(Postgres) │
  │   :3000   │           │   :8000   │           │   :5432   │
  └───────────┘           └───────────┘           └───────────┘
   (No host ports exposed directly - 100% internal to dev-net)
                                ▲
                                │
            ┌───────────────────┴───────────────────┐
            │                                       │
            ▼                                       ▼
 ┌──────────────────────┐   Incident    ┌──────────────────────┐
 │     CODING AGENT     │   Dossiers    │     AI-OPS AGENT     │
 │       OpenCode       │◄──────────────┤    (Monitoring &     │
 │                      │               │  Auto-Remediation)   │
 └──────────┬───────────┘               └───────────┬──────────┘
            │                                       │
            └───────────────────┬───────────────────┘
                                ▼
                       ┌─────────────────┐
                       │     devctl      │
                       │ (Ops Engine CLI)│
                       └─────────────────┘
```

---

## 🌟 Core Pillars

1. **Remote Workstation Native**: Code from your phone or laptop via SSH & Browser. OpenCode runs continuously inside `tmux` on your server.
2. **Instant Wildcard Ingress (`devctl`)**: Run `devctl expose my-app 3000` to immediately get `https://my-app.dev-server.datakrib.com` with automated TLS.
3. **Zero Public Host Ports**: Containers never publish host ports (`0.0.0.0:3000`). All traffic stays private on the internal Docker network `dev-net`, and only Caddy communicates with the internet.
4. **Headless Visual & Diagnostic Testing (Playwright)**: OpenCode runs `devctl test my-app` to automatically capture console errors, network failures, and mobile/desktop screenshots.
5. **Autonomous AI-Ops Agent**: Background daemon monitors 24/7. It auto-remediates infrastructure glitches (Level 1-2) and builds structured **Incident Dossiers** for OpenCode when application bugs are detected (Level 3).
6. **Mobile Status Dashboard**: Real-time monitoring UI at `https://status.dev-server.datakrib.com`.

---

## 🚀 One-Command Turnkey Server Setup

On your Ubuntu/Debian server:

```bash
git clone https://github.com/yourusername/happy-galileo.git /opt/happy-galileo
cd /opt/happy-galileo
sudo bash scripts/setup-server.sh
```

### What this script sets up automatically:
- ✅ **System Dependencies**: Docker, Docker Compose, Caddy, Fail2ban, UFW, Tmux, Python 3, Node.js + Playwright, OpenCode CLI.
- ✅ **Internal Network**: Creates `dev-net` bridge network.
- ✅ **Firewall**: Locks down UFW (only SSH, HTTP 80, HTTPS 443 allowed).
- ✅ **Intrusion Prevention**: Activates Fail2ban jails for SSH and Caddy exploit probes.
- ✅ **Global CLI**: Installs `devctl` globally to `/usr/local/bin/devctl`.
- ✅ **Base Services**: Starts Caddy reverse proxy, AI-Ops monitor daemon, and Status Web Dashboard.

---

## 🧰 `devctl` CLI Reference

### Expose a Container Service
```bash
# Expose on dev namespace (https://vessel-api.dev-server.datakrib.com)
devctl expose vessel-api 8000

# Expose on staging namespace (https://vessel-api-staging.dev-server.datakrib.com)
devctl expose vessel-api 8000 --env staging

# Auto-detect container port
devctl expose frontend
```

### Hide a Service
```bash
devctl hide vessel-api
```

### List Active Services & URLs
```bash
devctl list
```
Output:
```text
===============================================================================================
SERVICE            ENV      PORT     STATUS       PUBLIC URL                                   
===============================================================================================
frontend           dev      3000     ● RUNNING    https://frontend.dev-server.datakrib.com     
vessel-api         dev      8000     ● RUNNING    https://vessel-api.dev-server.datakrib.com   
dashboard          prod     8888     ● RUNNING    https://status.dev-server.datakrib.com       
===============================================================================================
```

### Run Playwright Browser Tests
```bash
devctl test frontend
```
Output:
```markdown
### Browser Test Diagnostics: ✅ PASSED
- Target URL: https://frontend.dev-server.datakrib.com
- HTTP Status: `200`
- Load Time: `142ms`

#### 📸 Captured Screenshots:
- Desktop: `~/.devctl/screenshots/frontend/desktop.png`
- Mobile: `~/.devctl/screenshots/frontend/mobile.png`
```

### Manage Incident Dossiers
```bash
# List open incidents
devctl incident list

# View detailed diagnostic dossier & stack trace
devctl incident inspect INC-20260813-A1B2C3

# Claim incident by OpenCode
devctl incident claim INC-20260813-A1B2C3

# Resolve incident
devctl incident resolve INC-20260813-A1B2C3 --notes "Fixed null check in UserService"
```

### System Health Diagnostic
```bash
devctl doctor
```

---

## 🛡️ Autonomous AI-Ops Tiered Remediation

| Tier | Trigger | Autonomous Action |
| :--- | :--- | :--- |
| **Level 0 (Observe)** | Periodic HTTP probe OK | Log telemetry and response times. |
| **Level 1 (Safe Infra Fix)** | Container stopped / crashed | Auto-restart container (up to 3 times), re-sync Caddy route. |
| **Level 2 (Deployment Fix)** | Network desync / unreachable | Re-attach to `dev-net`, reload Caddy TLS configuration. |
| **Level 3 (Application Bug)** | HTTP 500 / JS runtime crash / connection failure | **Never touch app code.** Extract stack trace, git diff, and logs into an **Incident Dossier** (`.devctl/incidents/`) and alert OpenCode. |

---

## 🔄 Standard OpenCode Coding Loop

1. **Write Code**: Implement feature in application repository.
2. **Start Docker**: Ensure `networks: [dev-net]` in `docker-compose.yml` (no `ports:` section).
3. **Expose**: `devctl expose my-app 3000`.
4. **Test**: `devctl test my-app`.
5. **Fix & Verify**: Inspect Playwright output, fix code, and re-verify.

---

## 📱 Mobile Status Dashboard

Access live status directly from your phone browser:
```
https://status.dev-server.datakrib.com
```
Features:
- Live service health pills & response times.
- One-click copy for HTTPS URLs.
- Incident Dossier viewer with stack traces.
- Playwright mobile & desktop screenshot gallery.

---

## 🔒 Security Hardening Summary

- **UFW Firewall**: Default `deny` incoming. Only ports `22` (SSH), `80` (HTTP), and `443` (HTTPS) are open.
- **Fail2ban**: Bans repetitive SSH failures and scans for `.env`, `wp-admin`, or exploit probes.
- **Zero Exposed Host Ports**: Databases (PostgreSQL, Redis) and internal microservices have no host port bindings. They communicate exclusively over the private Docker bridge `dev-net`.
- **Capability-Based Agent Access**: OpenCode and AI-Ops use structured `devctl` commands with audit logging rather than raw unconstrained root privileges.
