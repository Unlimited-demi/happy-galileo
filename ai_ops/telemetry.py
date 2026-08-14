"""
Fleet Telemetry Streamer for AI-Ops Node Agent.
Periodically streams node health metrics, active services, container stats,
and open incidents to the Central Fleet Hub Dashboard.
"""

import os
import time
import json
import urllib.request
import urllib.error
import threading
from typing import Dict, Any, Optional

from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from devctl.core.incident_bus import IncidentBus
from ai_ops.docker_socket import DockerSocket


class FleetTelemetryStreamer:
    """Sends periodic heartbeats from this node to the central fleet hub."""

    def __init__(
        self,
        hub_url: Optional[str] = None,
        node_name: Optional[str] = None,
        fleet_key: Optional[str] = None,
        interval_seconds: int = 15,
    ):
        self.hub_url = hub_url or os.environ.get("CENTRAL_HUB_URL", "")
        self.node_name = node_name or os.environ.get("NODE_NAME", os.uname().nodename if hasattr(os, "uname") else "node-01")
        self.fleet_key = fleet_key or os.environ.get("FLEET_KEY", "default-fleet-key")
        self.interval_seconds = interval_seconds
        self.docker = DockerSocket()
        self.registry = DomainRegistry()
        self.bus = IncidentBus()
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def collect_node_telemetry(self) -> Dict[str, Any]:
        """Gather current node metrics and active services."""
        containers = self.docker.list_containers(all_containers=True)
        services = self.registry.list_services()
        open_incidents = self.bus.list_incidents(only_open=True)
        resolved_incidents = [i for i in self.bus.list_incidents(only_open=False) if i.get("state") == "RESOLVED"]

        mem_info = {}
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if parts[0] in ["MemTotal", "MemAvailable", "MemFree"]:
                        mem_info[parts[0]] = int(parts[1].strip().split()[0]) // 1024
        except Exception:
            pass

        # Build container lookup map by name
        container_map = {}
        for c in containers:
            c_image = c.get("Image", "unknown")
            version_tag = c_image.split(":")[-1] if ":" in c_image else "latest"
            names = c.get("Names", [])
            for n in names:
                clean_name = n.lstrip("/")
                container_map[clean_name] = {
                    "image": c_image,
                    "version": version_tag,
                    "status": c.get("Status", "RUNNING"),
                    "state": c.get("State", "running"),
                    "id": c.get("Id", "")[:12],
                }

        # Enrich registered services with container image & version
        enriched_services = []
        for svc in services:
            c_name = svc.get("container_name", svc.get("service_name"))
            c_info = container_map.get(c_name, {})
            enriched = {
                **svc,
                "image": c_info.get("image", svc.get("image", "custom/app:latest")),
                "version": c_info.get("version", "latest"),
                "container_status": c_info.get("status", "RUNNING"),
                "container_id": c_info.get("id", ""),
            }
            enriched_services.append(enriched)

        return {
            "node_name": self.node_name,
            "base_domain": Config.BASE_DOMAIN,
            "timestamp": time.time(),
            "status": "ONLINE",
            "containers_count": len(containers),
            "services_count": len(enriched_services),
            "services": enriched_services,
            "open_incidents_count": len(open_incidents),
            "open_incidents": open_incidents[:10],
            "resolved_incidents_count": len(resolved_incidents),
            "memory_mb": mem_info,
        }

    def send_heartbeat(self) -> bool:
        """Send one telemetry heartbeat to the Central Hub."""
        if not self.hub_url:
            return False

        payload = self.collect_node_telemetry()
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self.hub_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Fleet-Key": self.fleet_key,
                "X-Node-Name": self.node_name,
                "User-Agent": f"AI-Ops-Telemetry/{self.node_name}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status == 200
        except Exception as e:
            return False

    def start_background(self):
        """Start the background streaming loop."""
        if not self.hub_url:
            return

        self.running = True

        def _loop():
            while self.running:
                try:
                    self.send_heartbeat()
                except Exception:
                    pass
                time.sleep(self.interval_seconds)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background streaming loop."""
        self.running = False
