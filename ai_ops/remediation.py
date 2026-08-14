"""
Remediation Engine for AI-Ops.
Implements tiered autonomous operations (Level 0 - Level 3) with strict safety boundaries.
Uses Docker socket API directly (no docker CLI dependency).
"""

from typing import Dict, Any
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

    def handle_health_result(self, health: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process health result and execute appropriate tiered action.

        Level 0: Healthy → Observe
        Level 1: Container stopped → Auto-restart
        Level 2: Network disconnected → Reconnect to dev-net
        Level 3: Application bug / repeated crash → Escalate to OpenCode with full Incident Dossier
        """
        service_name = health.get("service_name", "")
        container_name = health.get("container_name", service_name)
        is_healthy = health.get("healthy", False)
        container_running = health.get("container_running", False)
        http_status = health.get("http_status")
        url = health.get("url", "")
        error_msg = health.get("error")
        failure_reasons = health.get("failure_reasons", [])
        new_restarts = health.get("new_restarts", 0)
        oom_killed = health.get("oom_killed", False)

        # Level 0: Healthy
        if is_healthy:
            self.restart_tracker[service_name] = 0
            return {"level": 0, "action": "OBSERVE", "status": "HEALTHY"}

        reasons_str = "; ".join(failure_reasons) if failure_reasons else f"HTTP {http_status or 'DEAD'}"
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

        # Detect if this is a crash-loop (container auto-restarts but keeps crashing)
        if new_restarts > 0 or oom_killed:
            print(f"[Level 3] Container crash detected — restarts: {new_restarts}, OOM: {oom_killed}")

        # Level 3: Application Bug → Escalate to OpenCode with Incident Dossier
        print(f"[Level 3] Building Incident Dossier for OpenCode...")
        evidence = self.dossier_builder.build_evidence(
            service_name=service_name,
            container_name=container_name,
            http_status=http_status,
            failing_url=url,
            error_message=error_msg,
            failure_reasons=failure_reasons,
        )
        recommendation = self.dossier_builder.generate_recommendation(evidence)

        # Check for existing open incident to avoid duplicates
        existing_incidents = self.incident_bus.list_incidents(only_open=True)
        for inc in existing_incidents:
            if inc.get("service_name") == service_name:
                print(f"[Level 3] Active incident already open: {inc['id']}")
                return {"level": 3, "action": "ALREADY_REPORTED", "incident_id": inc["id"]}

        # Determine severity
        severity = "HIGH"
        if oom_killed:
            severity = "CRITICAL"
        elif new_restarts >= 3:
            severity = "CRITICAL"
        elif http_status and http_status >= 500:
            severity = "HIGH"

        # Create new incident
        title = f"Service '{service_name}' failing"
        if oom_killed:
            title += " — OOM killed (memory exhaustion)"
        elif new_restarts > 0:
            title += f" — crashed and restarted {new_restarts}x"
        elif http_status:
            title += f" — HTTP {http_status}"
        else:
            title += " — unreachable"

        incident = self.incident_bus.create_incident(
            service_name=service_name,
            title=title,
            severity=severity,
            level=3,
            evidence=evidence,
            recommendation=recommendation,
        )

        print(f"[INCIDENT CREATED] {incident['id']} — {title}")
        print(f"  Dossier: ~/.devctl/incidents/{incident['id']}.md")
        print(f"  Claim:   devctl incident claim {incident['id']}")

        return {
            "level": 3,
            "action": "ESCALATE_TO_OPENCODE",
            "incident_id": incident["id"],
            "dossier": f"{incident['id']}.md",
        }
