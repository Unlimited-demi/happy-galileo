# 🔬 AI-Ops Operations Guide: Detect → Classify → Remediate → Fleet

This document explains exactly how the platform detects problems, classifies them,
fixes them, and how the master node and sub-nodes connect and stay connected.

---

## 1. How Problems Are Detected

Detection runs on **two time horizons** — instant failures and gradual degradation.

### 1a. Instant detection (every cycle, default 15s)

The AI-Ops daemon (`ai_ops/daemon.py`) checks every registered service each cycle
via the Docker Engine socket (`/var/run/docker.sock`) — no agents inside your
app containers, no SDK instrumentation required:

| Signal | Source |
| :--- | :--- |
| Container stopped / crashed / exited | `GET /containers/{id}/json` → `State.Running` |
| OOM kill (memory exhaustion) | `State.OOMKilled` |
| Unexpected restarts since last cycle | `RestartCount` delta |
| Docker `HEALTHCHECK` failing | `State.Health.Status` |
| Runtime errors in logs | Log scan → `AnomalyClassifier` (see §2) |

### 1b. Trend detection (every ~5 min, new)

Point-in-time checks can't see a service that is *slowly* dying. Each cycle the
daemon also records a time-series sample per service into a local SQLite store
(`~/.devctl/metrics.db`, module `ai_ops/metrics_store.py`):

- **Latency** — internal HTTP probe to `container:port` over `dev-net`
- **Memory / CPU** — one-shot `GET /containers/{id}/stats`
- **Health state & restart count**

Every `TREND_CHECK_INTERVAL_CYCLES` (default 20 cycles ≈ 5 min) it compares the
recent slice of a rolling window against its earlier baseline and raises:

| Warning | Trigger (defaults) |
| :--- | :--- |
| `MEMORY_CREEP` | recent avg > 1.3× baseline **and** grew ≥ 50MB |
| `LATENCY_DRIFT` | recent avg > 1.5× baseline **and** grew ≥ 200ms |
| `RESTART_CHURN` | 3+ restarts inside the window |
| `FLAPPING` | health flipped 4+ times inside the window |

Verdicts are written to `~/.devctl/trends.json`, served by the dashboard at
`GET /api/metrics`, and streamed to the fleet hub in every heartbeat.
Samples older than `METRICS_RETENTION_HOURS` (default 7 days) are pruned.

---

## 2. How Problems Are Classified

`ai_ops/classifier.py` is a **language-agnostic grammar engine** — no LLM, no
API calls, no vendor hardcoding. Pipeline per log line:

1. **Noise filtering** — access logs, scanner probes, daemon lifecycle chatter,
   and self-monitoring output are discarded (prevents feedback loops).
2. **Operator-defined error patterns** *(new)* — your own regexes, checked first.
3. **Config / DB crash grammars** — Caddyfile errors, Postgres auth failures, …
4. **Stack-frame signatures** — Python tracebacks, JS/Go/JVM/Rust frames, panics.
5. **Universal exception grammar** — `[Anything]Error|Exception|Panic: message`.
6. **HTTP 5xx / 429 upstream failures** and **POSIX network errors**
   (`ECONNREFUSED`, `ETIMEDOUT`, …).

### Tuning classification in production (no code changes)

Drop regex files into the state directory (`~/.devctl/` — re-read every 60s):

```
~/.devctl/noise_patterns.txt   # one regex per line → matching lines are IGNORED
~/.devctl/error_patterns.txt   # one regex per line → matching lines raise incidents
```

Lines starting with `#` are comments; invalid regexes are skipped with a warning.
This is how you battle-test the classifier against your own log diversity.

---

## 3. How Problems Are Remediated (the tier ladder)

`ai_ops/remediation.py` walks a strict ladder — **infrastructure is fixed
autonomously, application code is never touched autonomously**:

| Tier | Condition | Autonomous action |
| :--- | :--- | :--- |
| **L0 Observe** | Healthy | Record metrics, clear episode tracking. |
| **L1 Restart** | Container stopped/crashed | Restart via Docker API, max `MAX_AUTO_RESTARTS` (3) per episode. |
| **L2 Network resync** *(now implemented)* | Container running but detached from `dev-net` | Re-attach to `dev-net` + reload Caddy (via Docker exec API). Applied once per unhealthy episode, then escalates. |
| **L3 Escalate** | App bug / L1-L2 exhausted | Build Incident Dossier (stack trace, logs, git context, compose target) → auto-dispatch OpenCode in tmux. One incident per service (dedup guard, synced with disk). |

Honest dispatch *(fixed)*: if OpenCode/tmux can't actually be launched, the
dispatcher now reports `PREPARED_NOT_DISPATCHED` instead of falsely claiming
success, and the daemon prints the manual command: `devctl dispatch <INC-ID>`.

---

## 4. Master Node ↔ Sub-Nodes: Connect, Stay Connected, Interact

### Topology

```
            MASTER NODE (Fleet Hub)                    SUB-NODES (workers)
  ┌───────────────────────────────────┐       ┌─────────────────────────────┐
  │ Dashboard  https://status.<domain>│       │ AI-Ops daemon (detect/heal) │
  │  • /api/fleet/nodes   (view all)  │◄──────┤ Telemetry streamer          │
  │  • /api/fleet/command (interact)  │ HTTPS │  POST heartbeat every 15s   │
  │  • /api/metrics       (trends)    │──────►│  ← response carries queued  │
  │  • FLEET_STORE + command queue    │       │    commands (whitelisted)   │
  └───────────────────────────────────┘       └─────────────────────────────┘
```

### How they connect and stay connected

- Each sub-node sets `CENTRAL_HUB_URL=https://status.<master-domain>/api/telemetry/ingest`,
  `NODE_NAME`, and `FLEET_KEY` in its environment.
- The telemetry streamer **pushes a heartbeat every 15s** (services, incidents,
  memory, and now trend verdicts). Every send is wrapped in try/except with the
  loop continuing forever — a network blip or hub restart never kills the node
  agent; it simply reconnects on the next tick.
- The hub authenticates each heartbeat via the `X-Fleet-Key` header and marks a
  node **OFFLINE after 90s without a heartbeat** (`/api/fleet/nodes`).
- Sub-nodes **never open inbound ports** for the fleet — all fleet traffic is
  outbound HTTPS from node to master.

### How you interact with a sub-node from the master (new)

Because nodes only talk outbound, commands piggyback on the heartbeat:

```bash
# Queue a command on the master (dashboard auth):
curl -X POST https://status.<master>/api/fleet/command \
  -H "Authorization: Bearer <dashboard-key>" \
  -d '{"node": "vm-02", "action": "restart_container", "target": "vessel-api"}'

# Inspect queue + execution results:
curl https://status.<master>/api/fleet/commands
```

The node receives the command inside its next heartbeat response (≤15s),
executes it, and immediately pushes a follow-up heartbeat with the result.

**Strict whitelist** (enforced on *both* hub and node — arbitrary shell is
rejected): `restart_container`, `resync_network`, `purge_incidents`.

For deeper interaction, the dashboard's worker console (tmux terminal streaming)
remains available on each node's own dashboard.

### Fleet hardening recommendations

- Set a strong unique `FLEET_KEY` per fleet (it authenticates heartbeats).
- Set `FLEET_TLS_VERIFY=true` once the master has a valid certificate —
  the permissive default is for bootstrap only.
- Give each node a stable, unique `NODE_NAME` (it keys the fleet store).

---

## New configuration reference

| Env var | Default | Purpose |
| :--- | :--- | :--- |
| `METRICS_ENABLED` | `true` | Master switch for time-series recording |
| `METRICS_RETENTION_HOURS` | `168` | Rolling retention (7 days) |
| `TREND_CHECK_INTERVAL_CYCLES` | `20` | Cycles between trend analyses |
| `TREND_WINDOW_HOURS` | `2` | Baseline-vs-recent comparison window |
| `TREND_MIN_SAMPLES` | `20` | Minimum samples before verdicts |
| `TREND_MEM_GROWTH_FACTOR` | `1.3` | Memory creep multiplier threshold |
| `TREND_LATENCY_FACTOR` | `1.5` | Latency drift multiplier threshold |

## New API endpoints (dashboard)

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `/api/metrics` | GET | Trend summary for all services |
| `/api/metrics?service=X&hours=2` | GET | Raw sample history + verdict for one service |
| `/api/fleet/command` | POST | Queue a whitelisted command for a sub-node |
| `/api/fleet/commands` | GET | Command queue + execution results |
