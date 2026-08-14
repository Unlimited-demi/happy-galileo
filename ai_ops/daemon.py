#!/usr/bin/env python3
"""
AI-Ops Monitoring & Auto-Remediation Daemon.
Continuously inspects service health, auto-heals infrastructure failures (L1-L2),
and escalates application bugs to OpenCode (L3) with full Incident Dossiers.
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
        self.cycle_count = 0

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        print("\n[*] Stopping AI-Ops daemon gracefully...")
        self.running = False

    def run_cycle(self):
        """Execute one health and remediation cycle."""
        self.cycle_count += 1
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        services_health = self.health_checker.check_all_services()

        if not services_health:
            if self.cycle_count % 20 == 0:  # Log idle status every 20 cycles
                print(f"[{now_str}] No registered services to monitor.")
            return

        healthy_count = 0
        unhealthy_count = 0

        for health in services_health:
            svc_name = health.get("service_name")
            if health.get("healthy"):
                healthy_count += 1
            else:
                unhealthy_count += 1
                # Trigger remediation pipeline
                result = self.remediation_engine.handle_health_result(health)
                action = result.get("action", "UNKNOWN")
                level = result.get("level", "?")
                print(f"[{now_str}] [{svc_name}] Level {level} → {action}")

        # Log periodic status summary
        if self.cycle_count % 10 == 0:
            print(f"[{now_str}] Cycle #{self.cycle_count}: {healthy_count} healthy, {unhealthy_count} unhealthy")

    def start(self):
        """Start the continuous background monitoring loop."""
        print("=" * 65)
        print("  AI-Ops Monitoring & Auto-Remediation Daemon")
        print(f"   Domain Scope:       *.{Config.BASE_DOMAIN}")
        print(f"   Internal Network:   {Config.DOCKER_NETWORK}")
        print(f"   Poll Interval:      {Config.MONITOR_INTERVAL_SECONDS}s")
        print(f"   Auto-Remediation:   {'ENABLED' if Config.AUTO_REMEDIATION_ENABLED else 'DISABLED'}")
        print(f"   Max Auto-Restarts:  {Config.MAX_AUTO_RESTARTS}")
        print("=" * 65)

        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[!] Error in AI-Ops monitoring cycle: {e}")
                import traceback
                traceback.print_exc()

            # Sleep in 1s increments to respond quickly to signals
            for _ in range(Config.MONITOR_INTERVAL_SECONDS):
                if not self.running:
                    break
                time.sleep(1)

        print("[*] AI-Ops daemon stopped.")


if __name__ == "__main__":
    daemon = AIOpsDaemon()
    daemon.start()
