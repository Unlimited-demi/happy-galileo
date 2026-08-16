"""
Dossier Builder for AI-Ops.
Extracts logs, stack traces, and git context to construct actionable Incident Dossiers.
Uses Docker socket API directly (no docker CLI dependency).
"""

import re
from typing import Dict, List, Any, Optional
from ai_ops.docker_socket import DockerSocket


class DossierBuilder:
    """Extracts diagnostic evidence and constructs incident reports."""

    def __init__(self):
        self.docker = DockerSocket()

    def extract_stack_trace(self, logs: str) -> str:
        """Extract the most relevant stack trace or error block from logs."""
        if not logs:
            return "No container logs available."

        lines = logs.splitlines()
        error_keywords = [
            "traceback",
            "error:",
            "error]",
            "exception",
            "fatal",
            "panic:",
            "typeerror",
            "referenceerror",
            "syntaxerror",
            "rangeerror",
            "cannot read properties",
            "undefined is not",
            "is not a function",
            "econnrefused",
            "connection refused",
            "internal server error",
            "oom",
            "out of memory",
            "killed",
            "segfault",
            "crash",
        ]

        filtered_lines = [l for l in lines if "ai-ops-healthchecker" not in l.lower() and "get /health" not in l.lower()]
        
        match_idx = -1
        for i, line in enumerate(filtered_lines):
            line_lower = line.lower().strip()
            if any(kw in line_lower for kw in error_keywords):
                match_idx = i
                break
                
        if match_idx >= 0:
            start = max(0, match_idx - 15)
            end = min(len(filtered_lines), match_idx + 16)
            return "\n".join(filtered_lines[start:end])

        return "\n".join(filtered_lines[-15:])

    def build_evidence(
        self,
        service_name: str,
        container_name: str,
        http_status: Optional[int] = None,
        failing_url: Optional[str] = None,
        error_message: Optional[str] = None,
        failure_reasons: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Gather evidence and return structured diagnostic payload."""
        logs = self.docker.get_logs(container_name, tail=150)
        stack_trace = self.extract_stack_trace(logs)
        container_info = self.docker.inspect_container(container_name)

        container_state = "unknown"
        restart_count = 0
        oom_killed = False
        started_at = ""
        finished_at = ""
        exit_code = None
        resource_usage = "unavailable"

        if container_info:
            state = container_info.get("State", {})
            container_state = state.get("Status", "unknown")
            restart_count = container_info.get("RestartCount", 0)
            oom_killed = state.get("OOMKilled", False)
            started_at = state.get("StartedAt", "")
            finished_at = state.get("FinishedAt", "")
            exit_code = state.get("ExitCode")

        if hasattr(self.docker, "stats_container"):
            try:
                stats = self.docker.stats_container(container_name)
                if stats:
                    resource_usage = stats
            except Exception:
                pass

        logs_lines = logs.splitlines() if logs else []
        last_logs = "\n".join(logs_lines[-50:]) if logs_lines else ""

        return {
            "service_name": service_name,
            "container_name": container_name,
            "container_state": container_state,
            "restart_count": restart_count,
            "oom_killed": oom_killed,
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "resource_usage": resource_usage,
            "status_code": http_status,
            "failing_url": failing_url,
            "error_message": error_message,
            "failure_reasons": failure_reasons or [],
            "stack_trace": stack_trace,
            "logs": last_logs,
        }

    def generate_recommendation(self, evidence: Dict[str, Any]) -> str:
        """Formulate specific recommendations for OpenCode based on error symptoms."""
        stack = evidence.get("stack_trace", "").lower()
        http_status = evidence.get("status_code")
        oom_killed = evidence.get("oom_killed", False)
        exit_code = evidence.get("exit_code")
        restart_count = evidence.get("restart_count", 0)

        if oom_killed or "out of memory" in stack or "oom" in stack:
            return "Container exceeded memory limit. Increase container memory limit or investigate memory leaks."
        
        if exit_code == 137:
            return "Container killed by OOM killer or SIGKILL. Check memory limits."
            
        if restart_count >= 3:
            return "Container is crash-looping. Check startup dependencies and initialization sequence."
            
        if exit_code == 1:
            return "Application exited with error. Check logs for initialization failures."

        if "econnrefused" in stack or "connection refused" in stack:
            return "Cannot connect to upstream dependency. Verify the dependency container is running and on the same network."

        if "cannot read properties" in stack or "typeerror" in stack or "undefined" in stack or "referenceerror" in stack:
            return "Application runtime error. Check the source code for null/undefined access patterns. Run unit tests to identify the failing code path."

        if "prismaclientinitializationerror" in stack or "database server at" in stack:
            svc = evidence.get('service_name', 'the service')
            return (
                "Database connection or Prisma initialization failure detected. "
                "1. Verify DATABASE_URL in docker-compose.yml and .env. "
                f"2. Check if the database dependency for {svc} is running on dev-net. "
                "3. Ensure PostgreSQL credentials (user, password, db name) match across services. "
                "4. If on Alpine Linux, ensure openssl is installed in Dockerfile (apk add --no-cache openssl)."
            )

        if "openssl" in stack and ("missing" in stack or "unable to require" in stack):
            return (
                "Prisma Engine OpenSSL runtime dependency error detected on Alpine Linux. "
                "1. Add 'RUN apk add --no-cache openssl libc6-compat' to the Dockerfile. "
                "2. Ensure prisma/schema.prisma includes binaryTargets = ['native', 'linux-musl-openssl-3.0.x']. "
                "3. Run npx prisma generate and rebuild the Docker image."
            )

        if http_status == 502 or http_status == 504:
            return (
                "Bad Gateway / Gateway Timeout. "
                "The upstream service is not responding on the configured port. "
                "1. Verify the application is binding to 0.0.0.0 (not 127.0.0.1). "
                "2. Check for process crashes in container logs. "
                "3. Verify the port matches what Caddy is proxying to."
            )

        if http_status and http_status >= 500:
            return (
                "Server-side error (HTTP 5xx). "
                "1. Review container logs and stack trace for the root cause. "
                "2. Check for unhandled exceptions in request handlers. "
                "3. Fix the bug, run regression tests, rebuild and redeploy."
            )

        return (
            "Service failure detected. "
            "1. Review container logs and the stack trace above. "
            "2. Identify the root cause from recent code changes. "
            "3. Checkout a fix branch, patch, test, and redeploy."
        )
