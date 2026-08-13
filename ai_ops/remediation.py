"""
Remediation Engine for AI-Ops.
Implements tiered autonomous operations (Level 0 - Level 3) with strict safety boundaries.
"""

from typing import Dict, Any
from devctl.core.config import Config
from devctl.core.docker_mgr import DockerManager
from devctl.core.caddy import CaddyManager
from devctl.core.incident_bus import IncidentBus
from .dossier_builder import DossierBuilder


class RemediationEngine:
    """Evaluates health failures and performs safe autonomous remediation or OpenCode escalation."""

    def __init__(self):
        self.docker_mgr = DockerManager()
        self.caddy_mgr = CaddyManager()
        self.incident_bus = IncidentBus()
        self.dossier_builder = DossierBuilder()
        self.restart_tracker: Dict[str, int] = {}

    def handle_health_result(self, health: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process health result and execute appropriate tiered action.
        """
        service_name = health.get("service_name", "")
        container_name = health.get("container_name", service_name)
        is_healthy = health.get("healthy", False)
        container_running = health.get("container_running", False)
        http_status = health.get("http_status")
        url = health.get("url", "")
        error_msg = health.get("error")

        # Level 0: Healthy
        if is_healthy:
            # Reset restart counter if service is healthy
            self.restart_tracker[service_name] = 0
            return {"level": 0, "action": "OBSERVE", "status": "HEALTHY"}

        print(f"\n[🚨 AI-Ops Alert] Unhealthy service detected: {service_name} (Status: {http_status or 'DEAD'})")

        # Level 1: Container crashed or stopped -> Auto-restart
        if not container_running:
            restarts = self.restart_tracker.get(service_name, 0)
            if Config.AUTO_REMEDIATION_ENABLED and restarts < Config.MAX_AUTO_RESTARTS:
                self.restart_tracker[service_name] = restarts + 1
                print(f"[*] [Level 1 Auto-Heal] Restarting container '{container_name}' (Attempt {restarts + 1}/{Config.MAX_AUTO_RESTARTS})...")
                restarted = self.docker_mgr.restart_container(container_name)
                return {
                    "level": 1,
                    "action": "RESTART_CONTAINER",
                    "success": restarted,
                    "attempt": restarts + 1,
                }

        # Level 3: Application Bug or Repeated Crash -> Escalate to OpenCode
        print(f"[*] [Level 3 Incident Escalation] Building Incident Dossier for OpenCode...")
        evidence = self.dossier_builder.build_evidence(
            service_name=service_name,
            container_name=container_name,
            http_status=http_status,
            failing_url=url,
            error_message=error_msg,
        )
        recommendation = self.dossier_builder.generate_recommendation(evidence)

        # Check if an open incident already exists for this service to avoid duplicate spam
        existing_incidents = self.incident_bus.list_incidents(only_open=True)
        for inc in existing_incidents:
            if inc.get("service_name") == service_name:
                print(f"[!] Active incident already open for {service_name}: {inc['id']}")
                return {"level": 3, "action": "ALREADY_REPORTED", "incident_id": inc["id"]}

        # Create new incident
        title = f"Service '{service_name}' failing with HTTP {http_status or 'CONNECTION_ERROR'}"
        incident = self.incident_bus.create_incident(
            service_name=service_name,
            title=title,
            severity="HIGH" if (http_status and http_status >= 500) else "MEDIUM",
            level=3,
            evidence=evidence,
            recommendation=recommendation,
        )

        print(f"[🚨] New Incident Created: {incident['id']}")
        print(f"    View dossier at: .devctl/incidents/{incident['id']}.md")
        print(f"    OpenCode can claim via: devctl incident claim {incident['id']}")

        return {
            "level": 3,
            "action": "ESCALATE_TO_OPENCODE",
            "incident_id": incident["id"],
            "dossier": f"{incident['id']}.md",
        }
