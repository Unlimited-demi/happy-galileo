"""
Health Checker module for AI-Ops.
Probes containers DIRECTLY over the internal dev-net Docker network,
not through the public HTTPS URL (which is unreachable from inside containers).
"""

import urllib.request
import urllib.error
import time
from typing import Dict, List, Any
from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from ai_ops.docker_socket import DockerSocket


class HealthChecker:
    """Performs HTTP and container-level health inspections."""

    def __init__(self):
        self.docker = DockerSocket()
        self.registry = DomainRegistry()
        # Track previous restart counts to detect NEW restarts
        self._prev_restart_counts: Dict[str, int] = {}

    def check_http_endpoint(self, url: str, timeout: int = 5) -> Dict[str, Any]:
        """Send HTTP probe to an internal container endpoint."""
        start = time.time()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AI-Ops-HealthChecker/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                duration_ms = int((time.time() - start) * 1000)
                return {
                    "healthy": res.status < 400,
                    "status_code": res.status,
                    "duration_ms": duration_ms,
                    "error": None,
                }
        except urllib.error.HTTPError as e:
            duration_ms = int((time.time() - start) * 1000)
            return {
                "healthy": False,
                "status_code": e.code,
                "duration_ms": duration_ms,
                "error": f"HTTP {e.code}: {e.reason}",
            }
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return {
                "healthy": False,
                "status_code": 0,
                "duration_ms": duration_ms,
                "error": str(e),
            }

    def check_service(self, service_info: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive health check on a registered service."""
        service_name = service_info.get("service_name", "")
        container_name = service_info.get("container_name", service_name)
        port = service_info.get("port", 80)
        public_url = service_info.get("url", "")

        # 1. Container health via Docker socket API
        container_info = self.docker.inspect_container(container_name)
        container_running = False
        container_state = "not_found"
        restart_count = 0
        oom_killed = False

        if container_info:
            state = container_info.get("State", {})
            container_running = state.get("Running", False)
            container_state = state.get("Status", "unknown")
            restart_count = container_info.get("RestartCount", 0)
            oom_killed = state.get("OOMKilled", False)

        # Detect NEW restarts since last check
        prev_restarts = self._prev_restart_counts.get(service_name, 0)
        new_restarts = max(0, restart_count - prev_restarts)
        self._prev_restart_counts[service_name] = restart_count

        # 2. HTTP probe DIRECTLY over internal Docker network (not public HTTPS)
        #    e.g. http://chaos-api:3000/health or http://demo-app:80/
        internal_url = f"http://{container_name}:{port}/health"
        http_result = self.check_http_endpoint(internal_url, timeout=Config.HTTP_TIMEOUT_SECONDS)

        # If /health returns 404, fall back to probing the root URL
        if http_result["status_code"] == 404:
            internal_url = f"http://{container_name}:{port}/"
            http_result = self.check_http_endpoint(internal_url, timeout=Config.HTTP_TIMEOUT_SECONDS)

        # 3. Determine overall health
        is_healthy = (
            container_running
            and http_result["healthy"]
            and not oom_killed
            and new_restarts == 0
        )

        # Build failure reasons
        failure_reasons = []
        if not container_running:
            failure_reasons.append(f"Container '{container_name}' is not running (state: {container_state})")
        if not http_result["healthy"]:
            failure_reasons.append(f"HTTP probe to {internal_url} failed: {http_result['error']}")
        if oom_killed:
            failure_reasons.append("Container was OOM killed (memory exhaustion)")
        if new_restarts > 0:
            failure_reasons.append(f"Container restarted {new_restarts} time(s) since last check (total: {restart_count})")

        return {
            "service_name": service_name,
            "container_name": container_name,
            "url": public_url,
            "internal_url": internal_url,
            "healthy": is_healthy,
            "container_running": container_running,
            "container_state": container_state,
            "restart_count": restart_count,
            "new_restarts": new_restarts,
            "oom_killed": oom_killed,
            "http_status": http_result["status_code"],
            "response_time_ms": http_result["duration_ms"],
            "error": http_result["error"],
            "failure_reasons": failure_reasons,
            "timestamp": time.time(),
        }

    def check_all_services(self) -> List[Dict[str, Any]]:
        """Check all registered services."""
        services = self.registry.list_services()
        results = []
        for svc in services:
            result = self.check_service(svc)
            results.append(result)
        return results
