"""
Playwright Runner interface for devctl.
Invokes headless browser diagnostics and formats results for OpenCode and terminal display.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from .config import Config, BASE_DIR


class PlaywrightRunner:
    """Executes headless visual and functional tests against exposed URLs."""

    def __init__(self, script_path: Optional[Path] = None):
        self.script_path = script_path or (BASE_DIR / "testing" / "runner.js")

    def run(self, url: str, service_name: str) -> Dict[str, Any]:
        """
        Run Playwright tests against an exposed service URL.
        Returns structured diagnostic report with screenshot paths and errors.
        """
        output_dir = Config.SCREENSHOTS_DIR / service_name
        output_dir.mkdir(parents=True, exist_ok=True)

        if not self.script_path.exists():
            return {
                "success": False,
                "url": url,
                "critical_issues": [f"Playwright runner script not found at {self.script_path}"],
                "console_errors": [],
                "network_failures": [],
                "screenshots": {},
            }

        cmd = ["node", str(self.script_path), url, str(output_dir)]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=60,
            )

            # Try to read generated report.json
            report_file = output_dir / "report.json"
            if report_file.exists():
                with open(report_file, "r", encoding="utf-8") as f:
                    return json.load(f)

            # Fallback parse stdout
            if res.stdout:
                try:
                    return json.loads(res.stdout.strip().splitlines()[-1])
                except Exception:
                    pass

            return {
                "success": False,
                "url": url,
                "critical_issues": [
                    f"Runner exited with code {res.returncode}: {res.stderr or res.stdout}"
                ],
                "console_errors": [],
                "network_failures": [],
                "screenshots": {},
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "url": url,
                "critical_issues": ["Playwright test execution timed out after 60s."],
                "console_errors": [],
                "network_failures": [],
                "screenshots": {},
            }
        except Exception as e:
            return {
                "success": False,
                "url": url,
                "critical_issues": [f"Failed to execute Playwright test: {str(e)}"],
                "console_errors": [],
                "network_failures": [],
                "screenshots": {},
            }

    @staticmethod
    def format_markdown_report(result: Dict[str, Any]) -> str:
        """Format test results as a clean Markdown report for OpenCode."""
        status_badge = "✅ PASSED" if result.get("success") else "❌ FAILED"
        url = result.get("url", "Unknown URL")
        http_status = result.get("httpStatus", "N/A")
        load_time = result.get("loadTimeMs", 0)

        lines = [
            f"### Browser Test Diagnostics: {status_badge}",
            f"- **Target URL:** {url}",
            f"- **HTTP Status:** `{http_status}`",
            f"- **Load Time:** `{load_time}ms`",
            "",
        ]

        critical = result.get("criticalIssues", [])
        if critical:
            lines.append("#### 🚨 Critical Issues Detected:")
            for issue in critical:
                lines.append(f"- {issue}")
            lines.append("")

        console_errors = result.get("consoleErrors", [])
        if console_errors:
            lines.append(f"#### 🛑 Console Errors ({len(console_errors)}):")
            for err in console_errors:
                lines.append(f"```text\n{err}\n```")
            lines.append("")

        network_fails = result.get("networkFailures", [])
        if network_fails:
            lines.append(f"#### ⚠️ Failed Network Requests ({len(network_fails)}):")
            for fail in network_fails:
                method = fail.get("method", "GET")
                fail_url = fail.get("url", "")
                status = fail.get("status") or fail.get("failure", "Failed")
                lines.append(f"- `{method} {fail_url}` -> **{status}**")
            lines.append("")

        screenshots = result.get("screenshots", {})
        if screenshots.get("desktop") or screenshots.get("mobile"):
            lines.append("#### 📸 Captured Screenshots:")
            if screenshots.get("desktop"):
                lines.append(f"- Desktop: `{screenshots['desktop']}`")
            if screenshots.get("mobile"):
                lines.append(f"- Mobile: `{screenshots['mobile']}`")
            lines.append("")

        return "\n".join(lines)
