"""
Remediation Engine for AI-Ops.
Implements tiered autonomous operations (Level 0 - Level 3) with strict safety boundaries.
Uses Docker socket API directly (no docker CLI dependency).
"""

from typing import Dict, Any, Optional, Set, Tuple
from devctl.core.config import Config
from devctl.core.incident_bus import IncidentBus
from ai_ops.docker_socket import DockerSocket
from ai_ops.dossier_builder import DossierBuilder


class RemediationEngine:
    """Evaluates health failures and performs safe autonomous remediation or OpenCode escalation."""

    def __init__(self):
        self.docker = DockerSocket()
        self.incident_bus = IncidentBus()
        self.dossier_builder = DossierBuilder()
        self.restart_tracker: Dict[str, int] = {}
        # In-memory dedup: set of service names with open incidents
        # This is the PRIMARY dedup guard — prevents spam even if file I/O is slow
        self._open_incidents: Set[str] = set()
        # Services already given a Level 2 network fix this unhealthy episode
        self._l2_fixed: Set[str] = set()

        # Seed from any existing incidents on disk
        try:
            existing = self.incident_bus.list_incidents(only_open=True)
            for inc in existing:
                svc = inc.get("service_name")
                if svc:
                    self._open_incidents.add(svc)
        except Exception:
            pass

    def _detect_proxy_container(self) -> Optional[Tuple[str, str]]:
        """
        Detect which reverse proxy is running on the node.
        Returns (container_name, proxy_type) or None if none found.
        """
        try:
            containers = self.docker.list_containers()
            for c in containers:
                name = c.get("Names", [""])[0].lstrip("/")
                if name in ("caddy", "nginx", "apache", "httpd"):
                    proxy_type = "caddy" if name == "caddy" else ("nginx" if name == "nginx" else "apache")
                    return name, proxy_type
        except Exception:
            pass
        return None

    def _try_level2_network_fix(self, service_name: str, container_name: str) -> Optional[Dict[str, Any]]:
        """
        Level 2 remediation: if the container is no longer attached to the
        internal Docker network, re-attach it and reload Caddy so its route
        resolves again. Returns a result dict when a fix was applied, else None.
        Applied at most once per service per unhealthy episode (cleared on healthy).
        """
        if service_name in self._l2_fixed:
            return None
        try:
            networks = self.docker.get_networks(container_name)
        except Exception:
            return None
        if not networks or Config.DOCKER_NETWORK in networks:
            return None  # attached (or container unknown) — not a network desync

        print(f"[Level 2] '{container_name}' detached from '{Config.DOCKER_NETWORK}' "
              f"(on: {', '.join(networks)}) — re-attaching and reloading proxy")
        reconnected = self.docker.connect_to_network(container_name, Config.DOCKER_NETWORK)
        proxy_reloaded = False
        if reconnected:
            proxy_info = self._detect_proxy_container()
            if proxy_info:
                proxy_name, proxy_type = proxy_info
                commands = {
                    "caddy": ["caddy", "reload", "--config", "/etc/caddy/Caddyfile"],
                    "nginx": ["nginx", "-s", "reload"],
                    "apache": ["apachectl", "graceful"],
                }
                cmd = commands.get(proxy_type)
                if cmd:
                    proxy_reloaded = self.docker.exec_in_container(proxy_name, cmd)
        self._l2_fixed.add(service_name)
        return {
            "level": 2,
            "action": "REATTACH_NETWORK",
            "success": reconnected,
            "proxy_reloaded": proxy_reloaded,
        }

    def handle_health_result(self, health: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process health result and execute appropriate tiered action.

        Level 0: Healthy → Observe, clear incident tracking
        Level 1: Container stopped → Auto-restart
        Level 3: Application bug / repeated crash → Escalate to OpenCode
        """
        service_name = health.get("service_name", "")
        container_name = health.get("container_name", service_name)
        is_healthy = health.get("healthy", False)
        container_running = health.get("container_running", False)
        url = health.get("url", "")
        log_error = health.get("log_error")
        failure_reasons = health.get("failure_reasons", [])
        new_restarts = health.get("new_restarts", 0)
        oom_killed = health.get("oom_killed", False)
        docker_health = health.get("docker_health", "none")

        # Level 0: Healthy — clear tracking
        if is_healthy:
            self.restart_tracker[service_name] = 0
            self._open_incidents.discard(service_name)
            self._l2_fixed.discard(service_name)
            return {"level": 0, "action": "OBSERVE", "status": "HEALTHY"}

        reasons_str = "; ".join(failure_reasons) if failure_reasons else "Container unhealthy"
        print(f"\n[AI-Ops ALERT] Unhealthy: {service_name} — {reasons_str}")

        # Level 1: Container crashed or stopped → Auto-restart
        if not container_running:
            restarts = self.restart_tracker.get(service_name, 0)
            if Config.AUTO_REMEDIATION_ENABLED and restarts < Config.MAX_AUTO_RESTARTS:
                self.restart_tracker[service_name] = restarts + 1
                print(f"[Level 1] Auto-restarting '{container_name}' (attempt {restarts + 1}/{Config.MAX_AUTO_RESTARTS})")
                restarted = self.docker.restart_container(container_name)
                return {
                    "level": 1,
                    "action": "RESTART_CONTAINER",
                    "success": restarted,
                    "attempt": restarts + 1,
                }

        # Level 2: Deployment / network desync → re-attach dev-net & re-sync Caddy
        # A container that is running but fell off the internal network (compose
        # recreate, manual disconnect) is an infra problem, not an app bug.
        if container_running and Config.AUTO_REMEDIATION_ENABLED:
            l2_result = self._try_level2_network_fix(service_name, container_name)
            if l2_result is not None:
                return l2_result

        # ── DEDUP GUARD ──
        # Only create ONE incident per service. Never spam.
        # Sync with disk — if an incident was resolved via CLI, remove from dedup set
        try:
            disk_open = {inc['service_name'] for inc in self.incident_bus.list_incidents(only_open=True)}
            self._open_incidents = disk_open
        except Exception:
            pass

        if service_name in self._open_incidents:
            return {"level": 3, "action": "ALREADY_REPORTED", "service": service_name}

        # Level 3: Application Bug → Escalate to OpenCode with Incident Dossier
        print(f"[Level 3] Building Incident Dossier for OpenCode...")
        evidence = self.dossier_builder.build_evidence(
            service_name=service_name,
            container_name=container_name,
            http_status=None,
            failing_url=url,
            error_message=log_error or reasons_str,
            failure_reasons=failure_reasons,
        )
        recommendation = self.dossier_builder.generate_recommendation(evidence)

        # Determine severity
        severity = "HIGH"
        if oom_killed:
            severity = "CRITICAL"
        elif new_restarts >= 3:
            severity = "CRITICAL"
        elif docker_health == "unhealthy":
            severity = "HIGH"

        # Create incident title from actual failure cause
        if oom_killed:
            title = f"Service '{service_name}' failing — OOM killed (memory exhaustion)"
        elif new_restarts > 0:
            title = f"Service '{service_name}' failing — crashed and restarted {new_restarts}x"
        elif not container_running:
            title = f"Service '{service_name}' container stopped or exited"
        elif docker_health == "unhealthy":
            title = f"Service '{service_name}' Docker HEALTHCHECK reports unhealthy"
        elif log_error:
            err_summary = log_error.strip()
            if "PrismaClientInitializationError" in err_summary:
                title = f"Service '{service_name}' database error — PrismaClientInitializationError"
            elif "TypeError" in err_summary:
                title = f"Service '{service_name}' runtime error — TypeError exception"
            elif "ECONNREFUSED" in err_summary:
                title = f"Service '{service_name}' connection refused — dependency down"
            else:
                title = f"Service '{service_name}' log error — {err_summary[:60]}"
        else:
            title = f"Service '{service_name}' health check failure"

        incident = self.incident_bus.create_incident(
            service_name=service_name,
            title=title,
            severity=severity,
            level=3,
            evidence=evidence,
            recommendation=recommendation,
        )

        # Mark in-memory dedup IMMEDIATELY
        self._open_incidents.add(service_name)

        print(f"[INCIDENT CREATED] {incident['id']} — {title}")
        print(f"  Dossier: ~/.devctl/incidents/{incident['id']}.md")

        # ── AUTO-DISPATCH: Launch OpenCode on THIS node to fix the bug ──
        # OpenCode is installed on the host via setup-server.sh (npm i -g opencode-ai)
        # It runs in a local tmux session: opencode-<incident_id>
        try:
            from ai_ops.dispatcher import IncidentDispatcher
            dispatcher = IncidentDispatcher()
            dispatch_result = dispatcher.dispatch(incident["id"])
            if dispatch_result.get("success"):
                print(f"  ⚡ AUTO-DISPATCHED: OpenCode session '{dispatch_result.get('session_name')}'")
                print(f"     Attach: tmux attach -t {dispatch_result.get('session_name')}")
            else:
                print(f"  ⚠ Auto-dispatch failed: {dispatch_result.get('error', 'unknown')}")
                print(f"  Manual: devctl dispatch {incident['id']}")
        except Exception as dispatch_err:
            print(f"  ⚠ Auto-dispatch error: {dispatch_err}")
            print(f"  Manual: devctl dispatch {incident['id']}")

        return {
            "level": 3,
            "action": "ESCALATE_AND_DISPATCH",
            "incident_id": incident["id"],
            "dossier": f"{incident['id']}.md",
        }

