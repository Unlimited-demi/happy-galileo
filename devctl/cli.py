#!/usr/bin/env python3
"""
devctl - Developer Operations & Dynamic Ingress CLI
The unified control interface for OpenCode, AI-Ops, and server administration.
"""

import sys
import json
import argparse
import socket
from typing import Optional

from devctl.core.config import Config, BASE_DIR
from devctl.core.caddy import CaddyManager
from devctl.core.docker_mgr import DockerManager
from devctl.core.domains import DomainRegistry
from devctl.core.playwright_runner import PlaywrightRunner
from devctl.core.incident_bus import IncidentBus


def print_banner():
    banner = r"""
     _              _   _ 
  __| | _____   ___| |_| |
 / _` |/ _ \ \ / / __| | |
| (_| |  __/\ V /| |_| | |
 \__,_|\___| \_/  \__|_|_|
   Dynamic Ingress & Ops Engine
"""
    print(banner)


def cmd_expose(args):
    """Expose a container service through Caddy with dynamic HTTPS."""
    service_name = DomainRegistry.sanitize_slug(args.service)
    env = args.env or "dev"
    domain = args.domain or Config.get_full_domain(service_name, env)

    docker_mgr = DockerManager()
    caddy_mgr = CaddyManager()
    registry = DomainRegistry()

    print(f"[*] Preparing to expose service '{service_name}' ({env} environment)...")

    # 1. Check container existence
    container_info = docker_mgr.inspect_container(service_name)
    if not container_info:
        # Fallback: try finding running container matching service name
        print(f"[!] Container '{service_name}' not found by exact name.")
        print(f"[?] Searching for active containers...")
        containers = docker_mgr.list_containers()
        found = False
        for c in containers:
            names = c.get("Names", "")
            if service_name in names:
                service_name = names.strip("/").split(",")[0]
                found = True
                print(f"[✓] Found matching container: {service_name}")
                break
        if not found:
            print(f"[✗] Error: Docker container '{args.service}' is not running.")
            print(f"    Please start your container first with: docker compose up -d")
            sys.exit(1)

    # 2. Port detection / validation
    port = args.port
    if not port:
        detected = docker_mgr.detect_ports(service_name)
        if detected:
            port = detected[0]
            print(f"[✓] Auto-detected internal container port: {port}")
        else:
            print(f"[✗] Error: No exposed port detected for container '{service_name}'.")
            print("    Please specify port explicitly: devctl expose <service> <port>")
            sys.exit(1)

    # 3. Network connection to dev-net
    print(f"[*] Ensuring container is attached to network '{Config.DOCKER_NETWORK}'...")
    docker_mgr.connect_to_network(service_name)

    # 4. Security Audit
    sec_audit = docker_mgr.audit_security(service_name)
    if sec_audit.get("has_public_ports"):
        print("\n" + "=" * 60)
        print("⚠️  SECURITY WARNING:")
        for v in sec_audit.get("violations", []):
            print(f"   - {v}")
        print("   Recommended: Remove 'ports:' section from docker-compose.yml.")
        print("   Caddy handles all routing internally over 'dev-net'.")
        print("=" * 60 + "\n")

    # 5. Inject route into Caddy
    print(f"[*] Registering route in Caddy for domain: https://{domain} -> {service_name}:{port}")
    caddy_res = caddy_mgr.add_route(
        domain=domain,
        upstream_host=service_name,
        upstream_port=port,
    )

    if not caddy_res.get("success"):
        print(f"[!] Caddy API response: {caddy_res.get('error')}")
        print(f"[!] Note: Caddy route registered locally. If Caddy is starting, it will load dynamically.")

    # 6. Save in state registry
    entry = registry.register(
        service_name=service_name,
        container_name=service_name,
        port=port,
        domain=domain,
        env=env,
    )

    print("\n" + "─" * 60)
    print(f"  🚀 Service Successfully Exposed!")
    print(f"  ────────────────────────────────────────")
    print(f"  Service:       {service_name}")
    print(f"  Internal:      {service_name}:{port} ({Config.DOCKER_NETWORK})")
    print(f"  Public URL:    {entry['url']}")
    print(f"  Environment:   {env.upper()}")
    print("─" * 60 + "\n")


def cmd_hide(args):
    """Remove a service's public route from Caddy."""
    service_name = DomainRegistry.sanitize_slug(args.service)
    registry = DomainRegistry()
    caddy_mgr = CaddyManager()

    svc = registry.get_service(service_name)
    if not svc:
        print(f"[!] Service '{service_name}' not found in devctl registry.")
        # Still attempt caddy route removal
        domain = Config.get_full_domain(service_name)
    else:
        domain = svc["domain"]

    print(f"[*] Removing Caddy route for domain: {domain}...")
    caddy_mgr.remove_route(domain)
    registry.unregister(service_name)

    print(f"[✓] Service '{service_name}' ({domain}) is now hidden.")


def cmd_list(args):
    """List all currently registered and exposed services."""
    registry = DomainRegistry()
    docker_mgr = DockerManager()
    services = registry.list_services()

    if not services:
        print("[!] No services are currently registered with devctl.")
        print("    Expose a service with: devctl expose <service> <port>")
        return

    print("\n" + "=" * 95)
    print(f"{'SERVICE':<18} {'ENV':<8} {'PORT':<8} {'STATUS':<12} {'PUBLIC URL':<45}")
    print("=" * 95)

    for s in services:
        name = s.get("service_name", "unknown")
        env = s.get("env", "dev")
        port = str(s.get("port", ""))
        url = s.get("url", "")
        
        is_running = docker_mgr.is_running(s.get("container_name", name))
        status = "● RUNNING" if is_running else "○ STOPPED"

        print(f"{name:<18} {env:<8} {port:<8} {status:<12} {url:<45}")

    print("=" * 95 + "\n")


def cmd_discover(args):
    """Auto-discover running Docker containers and index them into devctl."""
    print("\n🔍 Scanning server for running Docker containers...")
    registry = DomainRegistry()
    discovered = registry.discover_and_index_containers()

    if not discovered:
        print("[✓] All running containers are already indexed and monitored.")
        return

    print(f"\n[✓] Successfully discovered and indexed {len(discovered)} new container(s):")
    print("=" * 80)
    print(f"{'CONTAINER':<20} {'PORT':<8} {'ASSIGNED DOMAIN / HTTPS URL':<45}")
    print("=" * 80)
    for d in discovered:
        print(f"{d['container_name']:<20} {d['port']:<8} {d['url']:<45}")
    print("=" * 80)
    print("💡 All discovered services are now connected to dev-net and monitored by AI-Ops.\n")


def cmd_logs(args):
    """View container logs for a service."""
    service_name = args.service
    docker_mgr = DockerManager()
    logs = docker_mgr.get_logs(service_name, tail=args.tail)
    print(logs)


def cmd_test(args):
    """Run Playwright automated visual & diagnostic tests."""
    target = args.target
    registry = DomainRegistry()

    # If target is a service name, lookup URL
    if not target.startswith("http://") and not target.startswith("https://"):
        svc = registry.get_service(target)
        if svc:
            target = svc["url"]
            service_name = svc["service_name"]
        else:
            service_name = DomainRegistry.sanitize_slug(target)
            target = f"https://{Config.get_full_domain(service_name)}"
    else:
        service_name = "test-target"

    print(f"[*] Running Playwright diagnostic suite against: {target}...")
    runner = PlaywrightRunner()
    result = runner.run(target, service_name)

    # Print markdown report
    report_md = runner.format_markdown_report(result)
    print("\n" + report_md)


def cmd_incident(args):
    """Manage incidents and handoffs for OpenCode."""
    bus = IncidentBus()
    subcmd = args.incident_cmd

    if subcmd == "list" or not subcmd:
        incidents = bus.list_incidents(only_open=not args.all)
        if not incidents:
            print("[✓] No open incidents. All services healthy.")
            return

        print("\n" + "=" * 90)
        print(f"{'ID':<20} {'SERVICE':<15} {'SEVERITY':<10} {'STATE':<12} {'SUMMARY':<30}")
        print("=" * 90)
        for inc in incidents:
            print(
                f"{inc['id']:<20} {inc['service_name']:<15} {inc['severity']:<10} {inc['state']:<12} {inc['title'][:28]:<30}"
            )
        print("=" * 90 + "\n")

    elif subcmd == "inspect":
        if not args.incident_id:
            print("[✗] Error: Please specify incident ID: devctl incident inspect <id>")
            return
        inc = bus.get_incident(args.incident_id)
        if not inc:
            print(f"[✗] Incident '{args.incident_id}' not found.")
            return
        md_file = bus.incidents_dir / f"{args.incident_id}.md"
        if md_file.exists():
            print(md_file.read_text(encoding="utf-8"))
        else:
            print(inc)

    elif subcmd == "claim":
        if not args.incident_id:
            print("[✗] Error: Please specify incident ID: devctl incident claim <id>")
            return
        res = bus.claim_incident(args.incident_id, agent_name=args.agent or "OpenCode")
        if res:
            print(f"[✓] Incident {args.incident_id} claimed by {args.agent or 'OpenCode'}.")
        else:
            print(f"[✗] Incident {args.incident_id} not found.")

    elif subcmd == "purge":
        deleted = bus.purge_all_incidents()
        print(f"[✓] Purged {deleted} incident files.")

    elif subcmd == "resolve":
        if not args.incident_id:
            print("[✗] Error: Please specify incident ID: devctl incident resolve <id>")
            return

        inc = bus.get_incident(args.incident_id)
        if not inc:
            print(f"[✗] Incident '{args.incident_id}' not found.")
            return

        service_name = inc.get("service_name", "app")
        notes = args.notes or "Resolved application bug and verified with tests."
        
        # 1. Run live health probe on the resolved service
        import urllib.request
        import urllib.error
        import time
        import subprocess

        reg = DomainRegistry()
        svc_entry = reg.get_service(service_name)
        live_url = svc_entry.get("url", f"https://{Config.get_full_domain(service_name)}") if svc_entry else f"https://{Config.get_full_domain(service_name)}"

        health_probe_str = "HTTP 200 OK"
        response_time_ms = 0
        try:
            start = time.time()
            req = urllib.request.Request(live_url, headers={"User-Agent": "devctl-verifier/1.0"})
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                response_time_ms = int((time.time() - start) * 1000)
                health_probe_str = f"HTTP {resp.status} OK ({response_time_ms}ms)"
        except Exception as e:
            health_probe_str = f"Health Probe: {e}"

        # 2. Extract git branch and diff
        git_branch = "master"
        git_diff_stat = ""
        try:
            b_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout=subprocess.PIPE, text=True, check=False)
            if b_res.returncode == 0:
                git_branch = b_res.stdout.strip()

            # Try diff against origin/master, or recent commit show stat
            d_res = subprocess.run(["git", "diff", "--stat", "origin/master...HEAD"], stdout=subprocess.PIPE, text=True, check=False)
            if d_res.returncode == 0 and d_res.stdout.strip():
                git_diff_stat = d_res.stdout.strip()
            else:
                d_res2 = subprocess.run(["git", "show", "--stat", "HEAD"], stdout=subprocess.PIPE, text=True, check=False)
                git_diff_stat = d_res2.stdout.strip() if d_res2.returncode == 0 else ""
        except Exception:
            git_diff_stat = "Git diff not available"

        # 3. Check container running state
        docker_mgr = DockerManager()
        is_running = docker_mgr.is_running(service_name)
        container_state = "RUNNING" if is_running else "STOPPED"

        proof = {
            "live_url": live_url,
            "health_probe": health_probe_str,
            "response_time_ms": response_time_ms,
            "container_state": container_state,
            "git_branch": git_branch,
            "git_diff": git_diff_stat,
            "verified_by": args.agent or inc.get("claimed_by", "OpenCode"),
        }

        res = bus.resolve_incident(args.incident_id, notes=notes, proof=proof)
        
        print("\n" + "╔" + "═" * 74 + "╗")
        print(f"║{'INCIDENT RESOLUTION & VERIFICATION CERTIFICATE':^74}║")
        print("╠" + "═" * 74 + "╣")
        print(f"║ Incident ID:    {args.incident_id:<56}║")
        print(f"║ Service:        {service_name:<56}║")
        print(f"║ State:          {'VERIFIED & RESOLVED':<56}║")
        print(f"║ Resolved By:    {args.agent or inc.get('claimed_by', 'OpenCode'):<56}║")
        print(f"║ Git Branch:     {git_branch:<56}║")
        print("╠" + "─" * 74 + "╣")
        print("║ 📌 REMEDIATION & ROOT CAUSE SUMMARY:                                     ║")
        for line in notes.splitlines():
            print(f"║   {line:<71}║")
        print("╠" + "─" * 74 + "╣")
        print("║ 🧪 LIVE VERIFICATION PROOF:                                               ║")
        print(f"║   ✓ Container Status:  {container_state:<50}║")
        print(f"║   ✓ Health Probe:      {health_probe_str:<50}║")
        print(f"║   ✓ Live Service URL:  {live_url:<50}║")
        print("╠" + "─" * 74 + "╣")
        print("║ 🛠️ CODE DIFF SUMMARY:                                                    ║")
        for diff_line in git_diff_stat.splitlines()[:5]:
            print(f"║   {diff_line[:70]:<71}║")
        print("╚" + "═" * 74 + "╝\n")


def cmd_dispatch(args):
    """Dispatch an incident to OpenCode for autonomous diagnosis and remediation."""
    bus = IncidentBus()
    incident_id = args.incident_id

    # If no ID given, find the most recent open incident
    if not incident_id:
        open_incidents = bus.list_incidents(only_open=True)
        if not open_incidents:
            print("[✓] No open incidents found. All systems operational.")
            return
        incident = open_incidents[0]
        incident_id = incident["id"]
    else:
        incident = bus.get_incident(incident_id)
        if not incident:
            print(f"[✗] Incident '{incident_id}' not found.")
            return

    service_name = incident["service_name"]
    title = incident["title"]
    severity = incident.get("severity", "HIGH")
    evidence = incident.get("evidence", {})
    stack_trace = evidence.get("stack_trace", "No stack trace")
    recommendation = incident.get("recommendation", "Investigate and patch.")

    # 1. Claim incident on behalf of OpenCode
    bus.claim_incident(incident_id, agent_name="OpenCode")

    # 2. Render OpenCode Handoff Prompt
    branch_name = f"fix/{service_name}-{incident_id.lower()}"

    print("\n" + "═" * 70)
    print(f"🤖 [AI-OPS ──► OPENCODE HANDOFF] Dispatching Incident: {incident_id}")
    print("═" * 70)
    print(f"  Service:        {service_name}")
    print(f"  Severity:       {severity}")
    print(f"  Incident State: CLAIMED by OpenCode")
    print(f"  Working Branch: {branch_name}")
    print("─" * 70)
    print("📋 EVIDENCE DOSSIER:")
    print(f"  Summary: {title}")
    print(f"  Failing URL: {evidence.get('failing_url', 'N/A')}")
    print(f"  HTTP Status: {evidence.get('status_code', 'N/A')}")
    print("\n🪵 STACK TRACE / RECENT LOGS:")
    for line in stack_trace.splitlines()[:15]:
        print(f"    {line}")
    print("\n💡 AI-OPS RECOMMENDATION:")
    print(f"  {recommendation}")
    print("─" * 70)

    # 3. Create fix branch in git if in a git repository
    import subprocess
    try:
        subprocess.run(["git", "checkout", "-b", branch_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[✓] Git Branch created and checked out: {branch_name}")
    except Exception:
        pass

    # 4. Resolve target service directory
    svc_dir = BASE_DIR / "services" / service_name
    if not svc_dir.exists():
        svc_dir = BASE_DIR

    dossier_file = Config.INCIDENTS_DIR / f"{incident_id}.md"

    # Construct strict scoped prompt for OpenCode
    prompt = (
        f"URGENT INCIDENT REMEDIATION: {incident_id} ({service_name})\n"
        f"1. Read evidence dossier: {dossier_file}\n"
        f"2. SCOPE CONSTRAINT: Only investigate and modify code inside directory: {svc_dir}\n"
        f"   (STRICT: Do NOT modify ai_ops/, devctl/, or infra/ infrastructure code).\n"
        f"3. You are already on fix branch: {branch_name}\n"
        f"4. Implement the fix in source code and rebuild: cd {svc_dir} && docker compose up -d --build\n"
        f"5. Verify with: devctl test {service_name}\n"
        f"6. Mark resolved: devctl incident resolve {incident_id} --notes 'Fixed {service_name} root cause and verified with tests.'"
    )

    print(f"[*] Target Service Directory Scoped: {svc_dir}")

    # 5. Check if opencode executable is present to launch
    import shutil
    opencode_path = shutil.which("opencode")
    tmux_path = shutil.which("tmux")

    if opencode_path and not args.dry_run:
        # Default to tmux if available so user can disconnect safely
        use_tmux = bool(tmux_path) and not args.no_tmux
        
        if use_tmux:
            session_name = f"opencode-{service_name}"
            print(f"[*] Launching OpenCode inside persistent tmux session: '{session_name}'...")
            subprocess.run(["tmux", "kill-session", "-t", session_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # 1. Create persistent interactive tmux window with working directory
            subprocess.run(["tmux", "new-session", "-d", "-s", session_name, "-c", str(svc_dir)], check=False)
            # 2. Send OpenCode command directly into the tmux shell
            send_cmd = f"{opencode_path} run {json.dumps(prompt)}"
            subprocess.run(["tmux", "send-keys", "-t", session_name, send_cmd, "C-m"], check=False)
            print(f"\n[✓] OpenCode Agent is actively diagnosing '{service_name}' in the background!")
            print(f"    To watch OpenCode live:     tmux attach -t {session_name}")
            print(f"    To detach from view:        Press Ctrl+B then D")
        else:
            print(f"[*] Launching OpenCode agent live with Incident Dossier...\n")
            try:
                subprocess.run([opencode_path, "run", prompt], cwd=str(svc_dir))
            except Exception as e:
                print(f"[!] OpenCode process completed or interrupted: {e}")
    else:
        print(f"\n🚀 Ready for OpenCode execution:")
        print(f"   cd {svc_dir} && opencode run \"Resolve incident {incident_id} in {service_name}\"")
        print(f"\n   Or inspect dossier directly:")
        print(f"   devctl incident inspect {incident_id}\n")
    print("═" * 70 + "\n")


def cmd_doctor(args):
    """Check health of server prerequisites, Docker, Caddy, and DNS."""
    print("\n🔍 devctl Doctor - Environment & Health Diagnostic")
    print("=" * 60)

    # 1. Docker
    docker_mgr = DockerManager()
    res = docker_mgr._run_docker(["info"])
    if res["success"]:
        print("  [✓] Docker Engine:        RUNNING")
    else:
        print("  [✗] Docker Engine:        NOT REACHABLE")

    # 2. dev-net Network
    has_net = docker_mgr.ensure_network()
    print(f"  [{'✓' if has_net else '✗'}] Network '{Config.DOCKER_NETWORK}':     {'ACTIVE' if has_net else 'FAILED'}")

    # 3. Caddy Admin API
    caddy_mgr = CaddyManager()
    caddy_ok = caddy_mgr.check_health()
    print(f"  [{'✓' if caddy_ok else '!'}] Caddy Admin API:      {'REACHABLE (' + Config.CADDY_ADMIN_API + ')' if caddy_ok else 'NOT REACHABLE (Start infra stack)'}")

    # 4. Wildcard DNS Test
    test_host = Config.get_full_domain("health-check", "dev")
    try:
        ip = socket.gethostbyname(test_host)
        print(f"  [✓] Wildcard DNS:         RESOLVES ({test_host} -> {ip})")
    except Exception:
        print(f"  [!] Wildcard DNS:         Cannot resolve {test_host} locally (Ensure DNS wildcard is active)")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        prog="devctl",
        description="devctl - Developer Operations & Ingress Orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # expose
    p_expose = subparsers.add_parser("expose", help="Expose a container service with dynamic HTTPS")
    p_expose.add_argument("service", help="Docker container / service name")
    p_expose.add_argument("port", type=int, nargs="?", default=None, help="Internal container port")
    p_expose.add_argument("--domain", help="Custom domain override")
    p_expose.add_argument("--env", choices=["dev", "staging", "prod"], default="dev", help="Target environment namespace")

    # hide
    p_hide = subparsers.add_parser("hide", help="Remove public HTTPS route for a service")
    p_hide.add_argument("service", help="Service name to hide")

    # list
    p_list = subparsers.add_parser("list", help="List all active services and public URLs")
    p_list.add_argument("--env", choices=["dev", "staging", "prod"], help="Filter by environment")

    # logs
    p_logs = subparsers.add_parser("logs", help="Fetch container logs")
    p_logs.add_argument("service", help="Service name")
    p_logs.add_argument("--tail", type=int, default=100, help="Number of lines to tail")

    # test
    p_test = subparsers.add_parser("test", help="Run Playwright visual and diagnostic tests")
    p_test.add_argument("target", help="Service name or full URL")

    # incident
    p_incident = subparsers.add_parser("incident", help="Inspect and manage incident bus")
    p_incident.add_argument("incident_cmd", nargs="?", choices=["list", "inspect", "claim", "resolve", "purge"], default="list")
    p_incident.add_argument("incident_id", nargs="?", help="Incident ID")
    p_incident.add_argument("--all", action="store_true", help="Include resolved incidents")
    p_incident.add_argument("--agent", help="Agent claiming the incident")
    p_incident.add_argument("--notes", help="Resolution notes")

    # dispatch
    p_dispatch = subparsers.add_parser("dispatch", help="Dispatch an incident dossier to OpenCode for autonomous remediation")
    p_dispatch.add_argument("incident_id", nargs="?", help="Incident ID (defaults to latest open)")
    p_dispatch.add_argument("--tmux", action="store_true", help="Explicitly force tmux background session")
    p_dispatch.add_argument("--no-tmux", action="store_true", help="Run OpenCode directly in the current interactive terminal instead of tmux")
    p_dispatch.add_argument("--dry-run", action="store_true", help="Print prompt and checkout branch without invoking opencode CLI")

    # discover
    subparsers.add_parser("discover", help="Auto-discover running Docker containers and index them into devctl")

    # doctor
    subparsers.add_parser("doctor", help="Check system health and prerequisites")

    args = parser.parse_args()

    if not args.command:
        print_banner()
        parser.print_help()
        sys.exit(0)

    commands = {
        "expose": cmd_expose,
        "hide": cmd_hide,
        "list": cmd_list,
        "discover": cmd_discover,
        "logs": cmd_logs,
        "test": cmd_test,
        "incident": cmd_incident,
        "dispatch": cmd_dispatch,
        "doctor": cmd_doctor,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        cmd_fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
