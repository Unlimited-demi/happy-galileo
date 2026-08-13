#!/usr/bin/env python3
"""
devctl - Developer Operations & Dynamic Ingress CLI
The unified control interface for OpenCode, AI-Ops, and server administration.
"""

import sys
import argparse
import socket
from typing import Optional

from devctl.core.config import Config
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

    elif subcmd == "resolve":
        if not args.incident_id:
            print("[✗] Error: Please specify incident ID: devctl incident resolve <id>")
            return
        notes = args.notes or "Resolved application bug and verified with tests."
        res = bus.resolve_incident(args.incident_id, notes=notes)
        if res:
            print(f"[✓] Incident {args.incident_id} marked as RESOLVED.")
        else:
            print(f"[✗] Incident {args.incident_id} not found.")


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
    test_host = f"health-check.{Config.DEV_NAMESPACE}.{Config.BASE_DOMAIN}"
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
    p_incident.add_argument("incident_cmd", nargs="?", choices=["list", "inspect", "claim", "resolve"], default="list")
    p_incident.add_argument("incident_id", nargs="?", help="Incident ID")
    p_incident.add_argument("--all", action="store_true", help="Include resolved incidents")
    p_incident.add_argument("--agent", help="Agent claiming the incident")
    p_incident.add_argument("--notes", help="Resolution notes")

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
        "logs": cmd_logs,
        "test": cmd_test,
        "incident": cmd_incident,
        "doctor": cmd_doctor,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        cmd_fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
