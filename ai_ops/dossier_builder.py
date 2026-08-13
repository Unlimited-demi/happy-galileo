"""
Dossier Builder for AI-Ops.
Extracts logs, stack traces, and git context to construct actionable Incident Dossiers for OpenCode.
"""

import re
import subprocess
from typing import Dict, Any, Optional
from devctl.core.docker_mgr import DockerManager


class DossierBuilder:
    """Extracts diagnostic evidence and constructs incident reports."""

    def __init__(self):
        self.docker_mgr = DockerManager()

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
            "exception",
            "fatal",
            "panic:",
            "typeerror",
            "referenceerror",
            "prismaclient",
            "sequelize",
            "connection refused",
            "internal server error",
        ]

        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in error_keywords):
                capture = True

            if capture:
                error_lines.append(line)
                if len(error_lines) > 40:  # Cap at 40 lines of stack trace
                    break

        if error_lines:
            return "\n".join(error_lines)

        # Return the last 25 lines if no specific keyword triggered
        return "\n".join(lines[-25:])

    def get_recent_git_commit(self) -> Optional[str]:
        """Fetch latest git commit message and hash if inside a repository."""
        try:
            res = subprocess.run(
                ["git", "log", "-1", "--oneline"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def build_evidence(
        self,
        service_name: str,
        container_name: str,
        http_status: Optional[int] = None,
        failing_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gather evidence and return structured diagnostic payload."""
        logs = self.docker_mgr.get_logs(container_name, tail=100)
        stack_trace = self.extract_stack_trace(logs)
        container_info = self.docker_mgr.inspect_container(container_name)
        git_commit = self.get_recent_git_commit()

        container_state = "unknown"
        if container_info:
            container_state = container_info.get("State", {}).get("Status", "unknown")

        return {
            "service_name": service_name,
            "container_name": container_name,
            "container_state": container_state,
            "status_code": http_status,
            "failing_url": failing_url,
            "error_message": error_message,
            "git_commit": git_commit or "Not available",
            "stack_trace": stack_trace,
            "logs": logs[-1500:] if logs else "",
        }

    def generate_recommendation(self, evidence: Dict[str, Any]) -> str:
        """Formulate specific recommendations for OpenCode based on error symptoms."""
        stack = evidence.get("stack_trace", "").lower()
        http_status = evidence.get("status_code")

        if "connection refused" in stack or "database" in stack or "prisma" in stack:
            return (
                "Database/dependency connection failure detected. "
                "Check DATABASE_URL / Redis environment variables, network connectivity to internal services on 'dev-net', "
                "and ensure database migrations have run."
            )
        elif "typeerror" in stack or "referenceerror" in stack or "undefined" in stack:
            return (
                "Application runtime JavaScript/TypeScript bug detected. "
                "Review the stack trace above to identify the failing method/file, patch the code, run regression tests, "
                "and redeploy the container."
            )
        elif http_status == 502 or http_status == 504:
            return (
                "Bad Gateway / Gateway Timeout detected. "
                "The upstream service inside the container is not listening on the configured port or failed during request processing. "
                "Verify the application server port binding (must listen on 0.0.0.0, not 127.0.0.1)."
            )
        else:
            return (
                "Application failure detected. Review recent code changes, container logs, "
                "run Playwright tests to reproduce the issue, and commit the fix."
            )
