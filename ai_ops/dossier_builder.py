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
        error_lines = []
        capture = False

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

        for line in lines:
            line_lower = line.lower().strip()
            if any(kw in line_lower for kw in error_keywords):
                capture = True

            if capture:
                error_lines.append(line)
                if len(error_lines) > 50:
                    break

        if error_lines:
            return "\n".join(error_lines)

        # Return the last 30 lines if no specific keyword triggered
        return "\n".join(lines[-30:])

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

        if container_info:
            state = container_info.get("State", {})
            container_state = state.get("Status", "unknown")
            restart_count = container_info.get("RestartCount", 0)
            oom_killed = state.get("OOMKilled", False)
            started_at = state.get("StartedAt", "")
            finished_at = state.get("FinishedAt", "")

        return {
            "service_name": service_name,
            "container_name": container_name,
            "container_state": container_state,
            "restart_count": restart_count,
            "oom_killed": oom_killed,
            "started_at": started_at,
            "finished_at": finished_at,
            "status_code": http_status,
            "failing_url": failing_url,
            "error_message": error_message,
            "failure_reasons": failure_reasons or [],
            "stack_trace": stack_trace,
            "logs": logs[-2000:] if logs else "",
        }

    def generate_recommendation(self, evidence: Dict[str, Any]) -> str:
        """Formulate specific recommendations for OpenCode based on error symptoms."""
        stack = evidence.get("stack_trace", "").lower()
        http_status = evidence.get("status_code")
        oom_killed = evidence.get("oom_killed", False)

        if oom_killed or "out of memory" in stack or "oom" in stack:
            return (
                "CRITICAL: Container was OOM killed (Out of Memory). "
                "This indicates a memory leak in the application. "
                "1. Check for unbounded arrays, caches, or event listener accumulation. "
                "2. Add memory limits to the container. "
                "3. Profile heap usage with --inspect flag. "
                "4. Fix the leak, rebuild, and redeploy."
            )
        elif "cannot read properties" in stack or "typeerror" in stack or "undefined" in stack:
            return (
                "Application runtime bug detected (TypeError / null reference). "
                "1. Review the stack trace to identify the failing file and line number. "
                "2. Add null checks or fix the data flow. "
                "3. Checkout a fix branch, patch the code, run tests. "
                "4. Rebuild and redeploy the container."
            )
        elif "econnrefused" in stack or "connection refused" in stack:
            return (
                "Upstream dependency connection failure. "
                "1. Check if the database/Redis/external service is running. "
                "2. Verify environment variables (DATABASE_URL, REDIS_URL). "
                "3. Ensure containers are on the same Docker network (dev-net)."
            )
        elif http_status == 502 or http_status == 504:
            return (
                "Bad Gateway / Gateway Timeout. "
                "The upstream service is not responding on the configured port. "
                "1. Verify the application is binding to 0.0.0.0 (not 127.0.0.1). "
                "2. Check for process crashes in container logs. "
                "3. Verify the port matches what Caddy is proxying to."
            )
        elif http_status and http_status >= 500:
            return (
                "Server-side error (HTTP 5xx). "
                "1. Review container logs and stack trace for the root cause. "
                "2. Check for unhandled exceptions in request handlers. "
                "3. Fix the bug, run regression tests, rebuild and redeploy."
            )
        else:
            return (
                "Service failure detected. "
                "1. Review container logs and the stack trace above. "
                "2. Identify the root cause from recent code changes. "
                "3. Checkout a fix branch, patch, test, and redeploy."
            )
