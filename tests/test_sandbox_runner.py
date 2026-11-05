"""
Unit tests for SandboxRunner.
Verifies change guardrails, secret scanning in diffs, ephemeral sandbox commands,
and PR dossier generation.
"""

import pytest
from ai_ops.sandbox_runner import SandboxRunner, SandboxSecurityException


class TestSandboxRunner:
    def test_disallowed_paths_blocked(self):
        """Sensitive files (.env, git hooks, private keys) must be rejected."""
        dirty_files = ["src/index.js", ".env", "config/settings.json"]
        is_valid, violations = SandboxRunner.validate_changed_files(dirty_files)
        assert is_valid is False
        assert any(".env" in v for v in violations)

        git_hook = [".git/hooks/pre-commit"]
        is_valid, violations = SandboxRunner.validate_changed_files(git_hook)
        assert is_valid is False
        assert any(".git/hooks" in v for v in violations)

        traversal = ["../../etc/shadow"]
        is_valid, violations = SandboxRunner.validate_changed_files(traversal)
        assert is_valid is False
        assert any("traversal" in v.lower() for v in violations)

    def test_safe_paths_allowed(self):
        """Standard application code files must pass validation."""
        safe_files = ["src/app.py", "components/Button.tsx", "package.json", "README.md"]
        is_valid, violations = SandboxRunner.validate_changed_files(safe_files)
        assert is_valid is True
        assert len(violations) == 0

    def test_secret_scanning_detects_credentials(self):
        """Diffs containing private keys or tokens must trigger detection."""
        diff_with_key = """
--- a/config.py
+++ b/config.py
@@ -1,3 +1,4 @@
+GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyzAB"
 def init():
     pass
"""
        violations = SandboxRunner.scan_diff_for_secrets(diff_with_key)
        assert len(violations) > 0
        assert any("GitHub" in v for v in violations)

        diff_with_rsa = """
--- a/cert.pem
+++ b/cert.pem
@@ -0,0 +1,2 @@
+-----BEGIN RSA PRIVATE KEY-----
+MIIEowIBAAKCAQEA0...
"""
        violations = SandboxRunner.scan_diff_for_secrets(diff_with_rsa)
        assert len(violations) > 0
        assert any("Private Key" in v for v in violations)

    def test_clean_diff_passes_secret_scan(self):
        """Standard code diffs without credentials must pass cleanly."""
        clean_diff = """
--- a/services/user.py
+++ b/services/user.py
@@ -10,3 +10,4 @@
-    if user is None:
+    if user is None or not user.is_active:
         raise UserNotFoundError("User is not active")
"""
        violations = SandboxRunner.scan_diff_for_secrets(clean_diff)
        assert len(violations) == 0

    def test_diff_size_limit(self):
        """Massive runaway diffs must be rejected."""
        short_diff = "\n".join(["+ line"] * 100)
        valid, msg = SandboxRunner.check_diff_size(short_diff)
        assert valid is True

        huge_diff = "\n".join(["+ line"] * 700)
        valid, msg = SandboxRunner.check_diff_size(huge_diff)
        assert valid is False
        assert "exceeds maximum allowable limit" in msg

    def test_sandbox_docker_cmd_security(self):
        """Sandbox docker run command must enforce strict non-root and capability limits."""
        cmd = SandboxRunner.build_sandbox_docker_cmd(
            workspace_dir="/home/user/repo",
            incident_id="INC-20261105-001",
            prompt="Fix the bug",
            network="none",
        )
        cmd_str = " ".join(cmd)

        assert "--user 1000:1000" in cmd_str
        assert "--cap-drop ALL" in cmd_str
        assert "--security-opt no-new-privileges:true" in cmd_str
        assert "--memory 2g" in cmd_str
        assert "--network none" in cmd_str
        assert "-v /home/user/repo:/workspace:rw" in cmd_str
        # Verify Docker socket is NEVER mounted
        assert "docker.sock" not in cmd_str

    def test_pull_request_dossier_formatting(self):
        """PR dossier must contain all required audit sections and rollback plans."""
        incident = {
            "id": "INC-20261105-001",
            "service_name": "checkout-api",
            "title": "Null pointer in payment handler",
            "severity": "CRITICAL",
            "evidence": {"error_message": "TypeError: Cannot read properties of undefined"},
        }
        dossier = SandboxRunner.format_pull_request_dossier(
            incident=incident,
            fix_branch="fix/checkout-api-INC-20261105-001",
            diff_text="+ fixed_line()",
            test_output="Playwright: 5 passed",
        )

        assert "checkout-api" in dossier["title"]
        assert "INC-20261105-001" in dossier["title"]
        assert dossier["base"] == "master"
        assert dossier["head"] == "fix/checkout-api-INC-20261105-001"
        assert "## 🤖 Autonomous Remediation Report (ARA)" in dossier["body"]
        assert "Rollback Plan" in dossier["body"]
        assert "Human Approval Gate" in dossier["body"] or "Review and merge this PR" in dossier["body"]
