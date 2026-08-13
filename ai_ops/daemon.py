#!/usr/bin/env python3
"""
AI-Ops Monitoring & Auto-Remediation Daemon.
Continuously inspects service health, auto-heals infrastructure failures (L1-L2),
and escalates application bugs to OpenCode (L3).
"""

import time
import signal
import sys
from datetime import datetime, timezone
from devctl.core.config import Config
from ai_ops.health_checker import HealthChecker
from ai_ops.remediation import RemediationEngine


class AIOpsDaemon:
    """The central autonomous operations monitoring daemon."""

    def __init__(self):
        self.health_checker = HealthChecker()
        self.remediation_engine = RemediationEngine()
        self.running = True

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        print("\n[*] Stopping AI-Ops daemon gracefully...")
        self.running = False

    def run_cycle(self):
        """Execute one health and remediation cycle."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        services_health = self.health_checker.check_all_services()

        if not services_health:
            # Idle cycle
            return

        for health in services_health:
            svc_name = health.get("service_name")
            if health.get("healthy"):
                # Service healthy
                pass
            else:
                # Trigger remediation
                self.remediation_engine.handle_health_result(health)

    def start(self):
        """Start the continuous background monitoring loop."""
        print("=" * 65)
        print("🤖 AI-Ops Monitoring & Auto-Remediation Daemon Started")
        print(f"   Domain Scope:       *.{Config.BASE_DOMAIN}")
        print(f"   Internal Network:   {Config.DOCKER_NETWORK}")
        print(f"   Poll Interval:      {Config.MONITOR_INTERVAL_SECONDS}s")
        print(f"   Auto-Remediation:   {'ENABLED' if Config.AUTO_REMEDIATION_ENABLED else 'DISABLED'}")
        print("=" * 65)

        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[!] Error in AI-Ops monitoring cycle: {e}")

            # Sleep in 1s increments to respond quickly to signals
            for _ in range(Config.MONITOR_INTERVAL_SECONDS):
                if not self.running:
                    break
                time.sleep(1)

        print("[*] AI-Ops daemon stopped.")


if __name__ == "__main__":
    daemon = AIOpsDaemon()
    daemon.start()
