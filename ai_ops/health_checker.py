"""
Health Checker module for AI-Ops.
Probes containers DIRECTLY over the internal dev-net Docker network,
inspects container state, and scans recent container logs for uncaught exceptions and 500 errors.
"""

import urllib.request
import urllib.error
import time
import re
from typing import Dict, List, Any, Optional
from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from ai_ops.docker_socket import DockerSocket


class HealthChecker:
    """Performs HTTP, container-level, and log-based health inspections."""

    def __init__(self):
        self.docker = DockerSocket()
        self.registry = DomainRegistry()
        # Track previous restart counts to detect NEW restarts
        self._prev_restart_counts: Dict[str, int] = {}
        # Track previous log length to only inspect fresh error logs
        self._last_scanned_log_fingerprint: Dict[str, str] = {}

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

    def scan_recent_logs_for_errors(self, container_name: str, tail: int = 30) -> Optional[str]:
        """Scan recent logs for uncaught exceptions, TypeError, 500s, or crashes."""
        logs = self.docker.get_logs(container_name, tail=tail)
        if not logs:
            return None

        error_patterns = [
            r"TypeError:.*",
            r"ReferenceError:.*",
            r"Cannot read properties of.*",
            r"UnhandledPromiseRejection.*",
            r"\[ERROR\].*",
            r"FATAL.*",
            r"panic:.*",
            r"PrismaClient.*",
            r"ECONNREFUSED.*",
        ]

        matched_errors = []
        for line in logs.splitlines():
            for pat in error_patterns:
                if re.search(pat, line, re.IGNORECASE):
                    matched_errors.append(line.strip())
                    break

        if matched_errors:
            # Return the most recent matched error line
            return matched_errors[-1]
        return None

    # Ports that are known to NOT speak HTTP — databases, caches, mail protocols
    NON_HTTP_PORTS = {
        3306, 5432, 6379, 11211, 27017, 5672, 15672,  # mysql, postgres, redis, memcached, mongo, rabbitmq
        25, 110, 143, 465, 587, 993, 995, 4190,        # SMTP, POP3, IMAP, SIEVE (mail)
    }

    # Container image names that are known non-HTTP internal services
    NON_HTTP_IMAGES = {
        "mariadb", "mysql", "postgres", "redis", "memcached", "mongo", "mongodb",
        "rabbitmq", "nats", "elasticsearch", "opensearch", "zookeeper", "kafka",
        "dovecot", "postfix", "rspamd", "clamd", "olefy", "solr", "unbound",
        "watchdog", "acme", "certdumper", "ofelia", "dockerize",
    }

    def _is_non_http_service(self, service_info: Dict[str, Any]) -> bool:
        """Determine if a service is a non-HTTP internal service (DB, cache, mail daemon)."""
        port = int(service_info.get("port", 80))
        if port in self.NON_HTTP_PORTS:
            return True

        # Check container image name for known non-HTTP software
        container_name = service_info.get("container_name", service_info.get("service_name", ""))
        image = service_info.get("image", container_name).lower()
        for keyword in self.NON_HTTP_IMAGES:
            if keyword in image or keyword in container_name.lower():
                return True

        return False

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

        # 2. Determine if this is a non-HTTP service
        is_non_http = self._is_non_http_service(service_info)

        http_result = {"healthy": True, "status_code": 0, "duration_ms": 0, "error": None}
        internal_url = f"tcp://{container_name}:{port}" if is_non_http else f"http://{container_name}:{port}/"

        if not is_non_http:
            # HTTP probe DIRECTLY over internal Docker network
            internal_url = f"http://{container_name}:{port}/health"
            http_result = self.check_http_endpoint(internal_url, timeout=Config.HTTP_TIMEOUT_SECONDS)

            # If /health returns 404, fall back to probing root URL
            if http_result["status_code"] == 404:
                internal_url = f"http://{container_name}:{port}/"
                http_result = self.check_http_endpoint(internal_url, timeout=Config.HTTP_TIMEOUT_SECONDS)

        # 3. Log scanning for runtime application errors
        log_error = self.scan_recent_logs_for_errors(container_name, tail=25)

        # 4. Determine overall health
        # Non-HTTP services: healthy if container is running and no OOM/restarts
        # HTTP services: also require HTTP probe to pass
        is_healthy = (
            container_running
            and (is_non_http or http_result["healthy"])
            and not oom_killed
            and new_restarts == 0
            and log_error is None
        )

        # Build failure reasons
        failure_reasons = []
        if not container_running:
            failure_reasons.append(f"Container '{container_name}' is not running (state: {container_state})")
        if not is_non_http and not http_result["healthy"]:
            failure_reasons.append(f"HTTP probe to {internal_url} failed: {http_result['error']}")
        if oom_killed:
            failure_reasons.append("Container was OOM killed (memory exhaustion)")
        if new_restarts > 0:
            failure_reasons.append(f"Container restarted {new_restarts} time(s) (total: {restart_count})")
        if log_error:
            failure_reasons.append(f"Log Error: {log_error}")

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
            "error": http_result["error"] or log_error,
            "failure_reasons": failure_reasons,
            "check_mode": "container-only" if is_non_http else "http+container",
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
