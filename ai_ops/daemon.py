#!/usr/bin/env python3
"""
AI-Ops Monitoring & Auto-Remediation Daemon.
Continuously inspects service health, auto-heals infrastructure failures (L1-L2),
and escalates application bugs to OpenCode (L3) with full Incident Dossiers.
"""

import json
import time
import signal
import sys
from datetime import datetime, timezone
from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from ai_ops.health_checker import HealthChecker
from ai_ops.remediation import RemediationEngine
from ai_ops.telemetry import FleetTelemetryStreamer
from ai_ops.metrics_store import MetricsStore, probe_latency


class AIOpsDaemon:
    """The central autonomous operations monitoring daemon."""

    def __init__(self):
        self.health_checker = HealthChecker()
        self.remediation_engine = RemediationEngine()
        self.telemetry = FleetTelemetryStreamer()
        self.registry = DomainRegistry()
        self.metrics = MetricsStore() if Config.METRICS_ENABLED else None
        self.running = True
        self.cycle_count = 0
        # Register signal handlers immediately so graceful shutdown works from t=0
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _record_metrics(self, health):
        """Record one time-series sample per service (latency, memory, CPU)."""
        if not self.metrics:
            return
        try:
            container_name = health.get("container_name", "")
            stats = self.health_checker.docker.stats_container(container_name) or {}
            probe = {"latency_ms": None, "status": None}
            if health.get("container_running"):
                probe = probe_latency(container_name, health.get("port", 80))
            self.metrics.record_sample(
                service=health.get("service_name", container_name),
                healthy=health.get("healthy", False),
                latency_ms=probe.get("latency_ms"),
                http_status=probe.get("status"),
                mem_bytes=stats.get("mem_bytes"),
                mem_limit=stats.get("mem_limit"),
                cpu_pct=stats.get("cpu_pct"),
                restart_count=health.get("restart_count", 0),
            )
        except Exception:
            pass  # metrics must never break the remediation loop

    def _check_trends(self):
        """Detect gradual degradation and persist verdicts for dashboard & fleet hub."""
        if not self.metrics:
            return
        try:
            summary = self.metrics.trend_summary(Config.TREND_WINDOW_HOURS)
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            for svc, verdict in summary.items():
                for warning in verdict.get("warnings", []):
                    print(f"[{now_str}] [DEGRADATION] {svc}: {warning['type']} — {warning['detail']}")
            trends_path = Config.DEVCTL_STATE_DIR / "trends.json"
            with open(trends_path, "w", encoding="utf-8") as f:
                json.dump({"generated_at": time.time(), "trends": summary}, f, indent=2)
            self.metrics.prune()
        except Exception as e:
            print(f"[!] Trend check failed: {e}")

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
            self._record_metrics(health)
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

        # Periodic trend / degradation analysis
        if self.cycle_count % Config.TREND_CHECK_INTERVAL_CYCLES == 0:
            self._check_trends()

    def start(self):
        """Start the continuous background monitoring loop."""
        print("=" * 65)
        print("  AI-Ops Monitoring & Auto-Remediation Daemon")
        print(f"   Domain Scope:       *.{Config.BASE_DOMAIN}")
        print(f"   Internal Network:   {Config.DOCKER_NETWORK}")
        print(f"   Poll Interval:      {Config.MONITOR_INTERVAL_SECONDS}s")
        print(f"   Auto-Remediation:   {'ENABLED' if Config.AUTO_REMEDIATION_ENABLED else 'DISABLED'}")
        print(f"   Max Auto-Restarts:  {Config.MAX_AUTO_RESTARTS}")
        print(f"   Fleet Telemetry:    {'STREAMING' if self.telemetry.hub_url else 'STANDALONE'}")
        print("=" * 65)

        # Start telemetry streamer thread
        self.telemetry.start_background()

        while self.running:
            try:
                # Periodically auto-discover new containers every 4 cycles
                if self.cycle_count % 4 == 0:
                    self.registry.discover_and_index_containers()
                self.run_cycle()
                self.telemetry.send_heartbeat()
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
