# OpenCode Development & AI-Ops Contract

This workstation is a persistent remote development server managed by **OpenCode** (Coding Agent), **AI-Ops** (Autonomous DevOps & Monitoring Agent), and **Caddy** (Dynamic TLS Ingress).

---

## 🛡️ Core Rules & Architecture

1. **Zero Public Host Ports Policy**:
   - Never publish container ports directly to the host (`ports: ["3000:3000"]`).
   - All services must run on the internal Docker bridge network `dev-net`.
   - Caddy is the **only** process bound to public ports `80` and `443`.

2. **Wildcard Subdomain Ingress**:
   - Scope: `*.dev-server.datakrib.com`
   - Every service is exposed via `devctl expose <service_name> <port>`:
     - Example: `devctl expose frontend 3000` -> `https://frontend.dev-server.datakrib.com`
     - Example: `devctl expose api 8000` -> `https://api.dev-server.datakrib.com`
     - Staging: `devctl expose api 8000 --env staging` -> `https://api-staging.dev-server.datakrib.com`

---

## 🔄 Standard Development Workflow

When implementing or modifying any frontend, API, or service:

```
Write Code ──► Docker Build / Up ──► devctl expose ──► devctl test (Playwright) ──► Fix Bugs ──► Complete
```

### Step 1: Docker Configuration
Ensure your `docker-compose.yml` connects services to `dev-net` with no host port mapping:
```yaml
services:
  app:
    build: .
    container_name: my-app
    restart: unless-stopped
    networks:
      - dev-net

networks:
  dev-net:
    external: true
```

### Step 2: Start & Expose Service
```bash
docker compose up -d
devctl expose my-app 3000
```

### Step 3: Run Playwright Diagnostic Tests
Do NOT just assume the application works. Run Playwright against the live HTTPS URL:
```bash
devctl test my-app
```
Playwright will automatically:
- Check for uncaught console errors (`window.onerror`, JS runtime crashes).
- Check for failed sub-requests (404 missing assets, 500 API responses, CORS failures).
- Capture desktop and mobile screenshots.

### Step 4: Inspect & Fix
If errors or visual defects are reported in the diagnostic output:
1. Inspect the stack trace / logs: `devctl logs my-app --tail 50`.
2. Fix the application code.
3. Restart container: `docker compose restart my-app`.
4. Re-run `devctl test my-app`.

---

## 🚨 Incident Handling & AI-Ops Protocol

AI-Ops monitors the server 24/7. When an application regression occurs, AI-Ops creates an **Incident Dossier** in `.devctl/incidents/`.

### How OpenCode handles incidents:

1. **Check for open incidents:**
   ```bash
   devctl incident list
   ```

2. **Claim the incident:**
   ```bash
   devctl incident claim INC-20260813-XXXX
   ```

3. **Inspect the diagnostic evidence & stack trace:**
   ```bash
   devctl incident inspect INC-20260813-XXXX
   ```

4. **Remediate the root cause:**
   - Investigate the specific file and line mentioned in the stack trace.
   - Implement the fix in the source code.
   - Run regression tests.
   - Redeploy the container.

5. **Verify and resolve:**
   ```bash
   devctl test <service_name>
   devctl incident resolve INC-20260813-XXXX --notes "Fixed null check in UserService and verified with Playwright"
   ```

---

## 🧰 CLI Command Quick Reference

| Command | Description |
| :--- | :--- |
| `devctl expose <service> <port>` | Dynamically route HTTPS wildcard domain to container |
| `devctl hide <service>` | Remove dynamic route from Caddy |
| `devctl list` | List active services, health status, and HTTPS URLs |
| `devctl logs <service>` | Tail container logs |
| `devctl test <service_or_url>` | Run headless Playwright diagnostic & visual tests |
| `devctl incident list` | List open incident dossiers |
| `devctl incident inspect <id>` | View full stack trace & AI-Ops evidence |
| `devctl incident claim <id>` | Assign incident to OpenCode |
| `devctl incident resolve <id>` | Mark incident as resolved |
| `devctl doctor` | Verify system health, Docker, Caddy API, and DNS |
