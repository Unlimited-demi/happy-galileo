"""
Sandbox Runner for OpenCode Autonomous Remediation.
Enforces security boundaries, resource limits, change guardrails,
secret scanning, and PR-only workflows for AI coding agents.

Security Contracts:
1. Ephemeral execution: Containers are destroyed upon completion.
2. Zero Docker Socket: Sandboxed agents CANNOT manage or interact with Docker.
3. Least Privilege: Unprivileged execution (UID 1000, cap-drop ALL, no-new-privileges).
4. Secret Scanning: Diffs are scanned before generating PRs.
5. PR-Only Changes: Never pushes directly to protected branches (main, master, prod).
"""

import os
import re
import fnmatch
from typing import Dict, List, Any, Tuple, Optional


class SandboxSecurityException(Exception):
    """Raised when an agent violates sandbox security policies or change guardrails."""
    pass


class SandboxRunner:
    """Manages secure, isolated execution of OpenCode coding tasks."""

    MAX_DIFF_LINES = 600
    SANDBOX_IMAGE = "serverguard-sandbox:latest"
    DEFAULT_TIMEOUT_SECONDS = 1800  # 30 minutes

    # Files that an autonomous agent is NEVER allowed to touch
    DISALLOWED_PATH_PATTERNS = [
        ".env*",
        "*.env",
        "*.pem",
        "*.key",
        "*.pfx",
        "*id_rsa*",
        "*id_ed25519*",
        ".git/hooks/*",
        ".git/config",
        "/etc/*",
        "infra/security/*",
        "devctl/core/auth.py",
    ]

    # Secret scanning regexes on diff additions
    SECRET_PATTERNS = [
        (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Cryptographic Private Key"),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
        (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"), "GitHub Personal Access Token"),
        (re.compile(r"github_pat_[A-Za-z0-9_]{22,255}"), "GitHub Fine-Grained Personal Access Token"),
        (re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"), "Slack API Token"),
        (re.compile(r"(?i)(password|secret_key|api_key|access_token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"), "Plaintext Credential Assignment"),
    ]

    @classmethod
    def validate_changed_files(cls, changed_files: List[str]) -> Tuple[bool, List[str]]:
        """
        Ensure no files being touched match disallowed patterns (secrets, hooks, system configs).
        Returns (is_valid, list_of_violations).
        """
        violations = []
        for file_path in changed_files:
            clean_path = file_path.strip().replace("\\", "/")
            # Prevent directory traversal
            if ".." in clean_path:
                violations.append(f"Illegal path traversal attempt: {clean_path}")
                continue

            for pattern in cls.DISALLOWED_PATH_PATTERNS:
                if fnmatch.fnmatch(clean_path, pattern) or fnmatch.fnmatch(os.path.basename(clean_path), pattern):
                    violations.append(f"Modification prohibited for sensitive file: {clean_path} (rule: {pattern})")
                    break

        return len(violations) == 0, violations

    @classmethod
    def scan_diff_for_secrets(cls, diff_text: str) -> List[str]:
        """
        Scan added lines (+) in a git diff for leaked secrets, keys, or passwords.
        Returns a list of violation messages.
        """
        violations = []
        for line in diff_text.splitlines():
            # Only scan added lines in the diff
            if line.startswith("+") and not line.startswith("+++"):
                content = line[1:].strip()
                for pattern, desc in cls.SECRET_PATTERNS:
                    if pattern.search(content):
                        violations.append(f"Detected potential secret ({desc}) in diff: {content[:40]}...")
                        break

        return violations

    @classmethod
    def check_diff_size(cls, diff_text: str) -> Tuple[bool, str]:
        """
        Ensure the diff is bounded and does not execute massive unchecked changes.
        """
        lines = diff_text.splitlines()
        if len(lines) > cls.MAX_DIFF_LINES:
            return False, f"Diff size ({len(lines)} lines) exceeds maximum allowable limit of {cls.MAX_DIFF_LINES} lines."
        return True, ""

    @classmethod
    def build_sandbox_docker_cmd(
        cls,
        workspace_dir: str,
        incident_id: str,
        prompt: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        network: str = "none",
    ) -> List[str]:
        """
        Build the secure 'docker run' command for an unprivileged ephemeral sandbox.
        Zero Docker socket mounts, cap-drop ALL, memory/cpu constrained.
        """
        container_name = f"sandbox-opencode-{incident_id}"

        cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--user", "1000:1000",
            "--security-opt", "no-new-privileges:true",
            "--cap-drop", "ALL",
            "--memory", "2g",
            "--cpus", "2.0",
            "--network", network,
            "-v", f"{workspace_dir}:/workspace:rw",
            "-e", f"INCIDENT_ID={incident_id}",
            "-e", "OPENCODE_SANDBOX=1",
            cls.SANDBOX_IMAGE,
            "opencode", "run", prompt, "--auto"
        ]
        return cmd

    @classmethod
    def format_pull_request_dossier(
        cls,
        incident: Dict[str, Any],
        fix_branch: str,
        diff_text: str,
        test_output: str,
        rollback_instructions: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Format a complete, honest Handover Report v2 as a GitHub Pull Request payload.
        Ensures human-in-the-loop review before code is applied to production.
        """
        incident_id = incident.get("id", "UNKNOWN")
        service_name = incident.get("service_name", "app")
        title = incident.get("title", "Autonomous Remediation Fix")
        severity = incident.get("severity", "MEDIUM")

        pr_title = f"[ARA Auto-Fix] {service_name}: {title} (#{incident_id})"

        diff_block = f"```diff\n{diff_text}\n```" if diff_text else "_No diff captured._"
        test_block = f"```\n{test_output}\n```" if test_output else "_Tests not executed or logs empty._"
        rollback_block = rollback_instructions or f"git checkout master && git branch -D {fix_branch}"

        body = f"""## 🤖 Autonomous Remediation Report (ARA)

### 📋 Incident Overview
- **Incident ID:** `{incident_id}`
- **Target Service:** `{service_name}`
- **Severity:** `{severity}`
- **Remediation Branch:** `{fix_branch}`

### 🔍 Root Cause & Evidence
{incident.get('evidence', {}).get('error_message') or title}

### 🛠️ Proposed Changes
{diff_block}

### 🧪 Verification Proof
{test_block}

### ⏪ Rollback Plan
To revert this change if unexpected behavior occurs:
```bash
{rollback_block}
```

---
> 🛡️ **Security Policy Enforcement:**
> This pull request was prepared by **OpenCode** in an unprivileged, ephemeral sandbox container.
> No changes have been pushed to production. Review and merge this PR to deploy through standard CI/CD.
"""
        return {
            "title": pr_title,
            "head": fix_branch,
            "base": "master",
            "body": body,
            "incident_id": incident_id,
            "service_name": service_name,
        }
