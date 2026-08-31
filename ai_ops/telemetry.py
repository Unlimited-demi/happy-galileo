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
        # Results of hub-issued commands, reported back on the next heartbeat
        self._command_results: list = []

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

        # Latest degradation-trend verdicts written by the AI-Ops daemon
        trends = {}
        try:
            trends_path = Config.DEVCTL_STATE_DIR / "trends.json"
            if trends_path.exists():
                trends = json.loads(trends_path.read_text(encoding="utf-8")).get("trends", {})
        except Exception:
            pass

        payload = {
            "node_name": self.node_name,
            "base_domain": Config.BASE_DOMAIN,
            "timestamp": time.time(),
            "status": "ONLINE",
            "containers_count": len(containers),
            "services_count": len(enriched_services),
            "services": enriched_services,
            "open_incidents_count": len(open_incidents),
            "open_incidents": open_incidents[:20],
            "resolved_incidents_count": len(resolved_incidents),
            "resolved_incidents": resolved_incidents[:20],
            "all_incidents": (open_incidents + resolved_incidents)[:30],
            "memory_mb": mem_info,
            "trends": trends,
        }
        if self._command_results:
            payload["command_results"] = self._command_results[-10:]
        return payload

    # ── Hub → Node command channel (piggybacked on heartbeat response) ──
    # The node never opens an inbound port: the hub queues commands, and this
    # streamer receives them in the heartbeat response and executes a strict
    # whitelist of infra actions. Arbitrary shell commands are NOT accepted.

    ALLOWED_COMMANDS = {"restart_container", "resync_network", "purge_incidents"}

    def _execute_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        action = command.get("action", "")
        target = command.get("target", "")
        cmd_id = command.get("id", "")
        result: Dict[str, Any] = {
            "id": cmd_id,
            "action": action,
            "target": target,
            "executed_at": time.time(),
            "success": False,
        }

        if action not in self.ALLOWED_COMMANDS:
            result["error"] = f"Action '{action}' is not in the node command whitelist"
            return result

        try:
            if action == "restart_container":
                result["success"] = self.docker.restart_container(target)
            elif action == "resync_network":
                reconnected = self.docker.connect_to_network(target, Config.DOCKER_NETWORK)
                # Detect which proxy is running and reload it
                proxy_reloaded = False
                proxy_type = None
                try:
                    containers = self.docker.list_containers()
                    for c in containers:
                        names = [n.lstrip("/") for n in c.get("Names", [])]
                        cname = names[0] if names else ""
                        if cname in ("caddy", "nginx", "apache", "httpd"):
                            proxy_type = "caddy" if cname == "caddy" else ("nginx" if cname == "nginx" else "apache")
                            reload_cmds = {
                                "caddy": ["caddy", "reload", "--config", "/etc/caddy/Caddyfile"],
                                "nginx": ["nginx", "-s", "reload"],
                                "apache": ["apachectl", "graceful"],
                            }
                            cmd = reload_cmds.get(proxy_type)
                            if cmd:
                                proxy_reloaded = self.docker.exec_in_container(cname, cmd)
                            break
                except Exception:
                    pass
                result["success"] = bool(reconnected)
                result["proxy_reloaded"] = proxy_reloaded
                result["proxy_type"] = proxy_type
            elif action == "purge_incidents":
                result["purged"] = self.bus.purge_all_incidents()
                result["success"] = True
        except Exception as e:
            result["error"] = str(e)

        print(f"[fleet] Executed hub command {action}({target}) → success={result['success']}")
        return result

    def _handle_pending_commands(self, response_body: str):
        try:
            data = json.loads(response_body) if response_body else {}
        except Exception:
            return
        pending = data.get("pending_commands") or []
        if not pending:
            return
        for command in pending[:10]:
            self._command_results.append(self._execute_command(command))
        self._command_results = self._command_results[-20:]
        # Push results back to the hub immediately instead of waiting a full interval
        try:
            self.send_heartbeat(handle_commands=False)
        except Exception:
            pass

    def send_heartbeat(self, handle_commands: bool = True) -> bool:
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
            import ssl
            tls_verify = os.environ.get("FLEET_TLS_VERIFY", "false").lower() == "true"
            if tls_verify:
                ctx = ssl.create_default_context()
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=5, context=ctx) as res:
                body = res.read().decode("utf-8", errors="replace")
                if res.status == 200 and handle_commands:
                    self._handle_pending_commands(body)
                return res.status == 200
        except Exception as e:
            print(f"[!] Telemetry heartbeat to {self.hub_url} failed: {e}")
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
