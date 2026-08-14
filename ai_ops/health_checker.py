"""
Health Checker module for AI-Ops.
Probes active HTTP endpoints, container statuses (via Docker socket), and resource metrics.
Designed to run inside a container WITHOUT the docker CLI binary.
"""

import urllib.request
import urllib.error
import ssl
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
        """Send probe to HTTP/HTTPS endpoint."""
        start = time.time()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AI-Ops-HealthChecker/1.0"},
        )
        # Allow self-signed certs during ACME provisioning
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as res:
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

    def check_health_endpoint(self, base_url: str, timeout: int = 5) -> Dict[str, Any]:
        """Probe the /health endpoint specifically for detailed status."""
        health_url = base_url.rstrip("/") + "/health"
        return self.check_http_endpoint(health_url, timeout)

    def check_service(self, service_info: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive health check on a registered service."""
        service_name = service_info.get("service_name", "")
        container_name = service_info.get("container_name", service_name)
        url = service_info.get("url", "")

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

        # 2. HTTP probe on root URL
        http_result = self.check_http_endpoint(url, timeout=Config.HTTP_TIMEOUT_SECONDS)

        # 3. Health endpoint probe (if root returned 200, also check /health)
        health_result = None
        if http_result["healthy"]:
            health_result = self.check_health_endpoint(url, timeout=Config.HTTP_TIMEOUT_SECONDS)

        # 4. Determine overall health
        # Unhealthy if: container not running, HTTP failed, OOM killed, or excessive restarts
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
            failure_reasons.append(f"HTTP probe failed: {http_result['error']}")
        if oom_killed:
            failure_reasons.append("Container was OOM killed (memory exhaustion)")
        if new_restarts > 0:
            failure_reasons.append(f"Container restarted {new_restarts} time(s) since last check (total: {restart_count})")

        return {
            "service_name": service_name,
            "container_name": container_name,
            "url": url,
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
            "health_endpoint": health_result,
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
