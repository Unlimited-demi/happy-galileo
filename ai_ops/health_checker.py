"""
Health Checker module for AI-Ops.
Probes active HTTP endpoints, container statuses, and resource metrics.
"""

import urllib.request
import urllib.error
import time
from typing import Dict, List, Any
from devctl.core.config import Config
from devctl.core.docker_mgr import DockerManager
from devctl.core.domains import DomainRegistry


class HealthChecker:
    """Performs HTTP and container-level health inspections."""

    def __init__(self):
        self.docker_mgr = DockerManager()
        self.registry = DomainRegistry()

    def check_http_endpoint(self, url: str, timeout: int = 5) -> Dict[str, Any]:
        """Send probe to HTTP/HTTPS endpoint."""
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
        url = service_info.get("url", "")

        # 1. Container health
        container_info = self.docker_mgr.inspect_container(container_name)
        container_running = False
        container_state = "not_found"
        restart_count = 0

        if container_info:
            state = container_info.get("State", {})
            container_running = state.get("Running", False)
            container_state = state.get("Status", "unknown")
            restart_count = container_info.get("RestartCount", 0)

        # 2. HTTP probe
        http_result = self.check_http_endpoint(url, timeout=Config.HTTP_TIMEOUT_SECONDS)

        # Overall health evaluation
        is_healthy = container_running and http_result["healthy"]

        return {
            "service_name": service_name,
            "container_name": container_name,
            "url": url,
            "healthy": is_healthy,
            "container_running": container_running,
            "container_state": container_state,
            "restart_count": restart_count,
            "http_status": http_result["status_code"],
            "response_time_ms": http_result["duration_ms"],
            "error": http_result["error"],
            "timestamp": time.time(),
        }

    def check_all_services(self) -> List[Dict[str, Any]]:
        """Check all registered services."""
        services = self.registry.list_services()
        results = []
        for svc in services:
            results.append(self.check_service(svc))
        return results
