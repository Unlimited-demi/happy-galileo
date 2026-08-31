"""
Health Checker module for AI-Ops.
Monitors ALL containers via Docker state inspection and log scanning.
Detects crashes, restarts, OOM kills, and runtime errors in container logs.
"""

import time
import re
from typing import Dict, List, Any, Optional
from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from ai_ops.docker_socket import DockerSocket
from ai_ops.classifier import AnomalyClassifier


class HealthChecker:
    """Monitors container health via Docker state and log error scanning."""

    def __init__(self):
        self.docker = DockerSocket()
        self.registry = DomainRegistry()
        self._prev_restart_counts: Dict[str, int] = {}
        self._prev_log_hashes: Dict[str, str] = {}

    def scan_logs_for_errors(self, container_name: str, tail: int = 40) -> Optional[str]:
        """Scan recent container logs for runtime errors, crashes, and exceptions."""
        logs = self.docker.get_logs(container_name, tail=tail)
        if not logs:
            return None

        # Dedup: skip if logs haven't changed since last scan
        log_hash = hashlib.md5(logs.encode("utf-8", errors="replace")).hexdigest()
        if self._prev_log_hashes.get(container_name) == log_hash:
            return None
        self._prev_log_hashes[container_name] = log_hash

        result = AnomalyClassifier.classify_log_error(container_name, logs)
        if result:
            err_snippet, err_category = result
            return f"[{err_category}] {err_snippet}"
        return None

    def check_container(self, service_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform health check on a container by inspecting Docker state and logs.
        
        Health is determined by:
        1. Container running state (from Docker Engine API)
        2. OOM kill detection
        3. Unexpected restart detection
        4. Docker HEALTHCHECK status (if container defines one)
        5. Log scanning for runtime errors and exceptions
        """
        service_name = service_info.get("service_name", "")
        container_name = service_info.get("container_name", service_name)
        port = service_info.get("port", 80)
        public_url = service_info.get("url", "")

        # 1. Container state from Docker Engine API
        container_info = self.docker.inspect_container(container_name)
        container_running = False
        container_state = "not_found"
        restart_count = 0
        oom_killed = False
        docker_health = "none"  # none = no HEALTHCHECK defined

        if container_info:
            state = container_info.get("State", {})
            container_running = state.get("Running", False)
            container_state = state.get("Status", "unknown")
            restart_count = container_info.get("RestartCount", 0)
            oom_killed = state.get("OOMKilled", False)

            # Check Docker's built-in HEALTHCHECK status if the container defines one
            health_obj = state.get("Health", {})
            if health_obj:
                docker_health = health_obj.get("Status", "none")  # healthy, unhealthy, starting

        # 2. Detect NEW restarts since last check cycle
        prev_restarts = self._prev_restart_counts.get(service_name, 0)
        new_restarts = max(0, restart_count - prev_restarts)
        self._prev_restart_counts[service_name] = restart_count

        # 3. Scan container logs for runtime errors
        log_error = self.scan_logs_for_errors(container_name, tail=30)

        # 4. Determine overall health
        is_healthy = (
            container_running
            and not oom_killed
            and new_restarts == 0
            and docker_health != "unhealthy"
            and log_error is None
        )

        # Build failure reasons list
        failure_reasons = []
        if not container_running:
            failure_reasons.append(f"Container '{container_name}' is not running (state: {container_state})")
        if oom_killed:
            failure_reasons.append("Container was OOM killed (memory exhaustion)")
        if new_restarts > 0:
            failure_reasons.append(f"Container restarted {new_restarts} time(s) since last check (total: {restart_count})")
        if docker_health == "unhealthy":
            failure_reasons.append("Docker HEALTHCHECK reports unhealthy")
        if log_error:
            failure_reasons.append(f"Log error detected: {log_error}")

        return {
            "service_name": service_name,
            "container_name": container_name,
            "url": public_url,
            "port": port,
            "healthy": is_healthy,
            "container_running": container_running,
            "container_state": container_state,
            "docker_health": docker_health,
            "restart_count": restart_count,
            "new_restarts": new_restarts,
            "oom_killed": oom_killed,
            "log_error": log_error,
            "failure_reasons": failure_reasons,
            "timestamp": time.time(),
        }

    def check_all_services(self) -> List[Dict[str, Any]]:
        """Check all registered services."""
        services = self.registry.list_services()
        results = []
        for svc in services:
            result = self.check_container(svc)
            results.append(result)
        return results
