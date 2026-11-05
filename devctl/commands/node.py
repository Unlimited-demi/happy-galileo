"""
Node Management & Fleet Enrollment Commands for devctl.
Allows satellite server nodes to securely enroll into Central Hub,
verify mutual connectivity, and stream telemetry without inbound ports.
"""

import os
import sys
import json
import time
import socket
import ssl
import platform
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from devctl.core.config import Config


class NodeManager:
    """Manages satellite node enrollment and configuration."""

    CONFIG_FILE = Config.DEVCTL_STATE_DIR / "fleet_node.json"

    @classmethod
    def get_default_node_name(cls) -> str:
        """Get default node name from environment or system hostname."""
        env_name = os.environ.get("NODE_NAME")
        if env_name:
            return env_name.strip()
        try:
            return socket.gethostname().split(".")[0].lower()
        except Exception:
            return "node-worker"

    @classmethod
    def normalize_hub_url(cls, hub_url: str) -> Tuple[str, str]:
        """
        Normalize Hub URL into (ingest_endpoint, base_url).
        Accepts:
          - https://status.dev-server.datakrib.com
          - https://status.dev-server.datakrib.com/
          - https://status.dev-server.datakrib.com/api/telemetry/ingest
        """
        raw = hub_url.strip().rstrip("/")
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = f"https://{raw}"

        if raw.endswith("/api/telemetry/ingest"):
            base_url = raw[: -len("/api/telemetry/ingest")]
            ingest_url = raw
        else:
            base_url = raw
            ingest_url = f"{raw}/api/telemetry/ingest"

        return ingest_url, base_url

    @classmethod
    def get_node_config(cls) -> Dict[str, Any]:
        """Read saved node configuration or fallback to environment variables."""
        if cls.CONFIG_FILE.exists():
            try:
                data = json.loads(cls.CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        # Fallback to environment variables
        hub_url = os.environ.get("CENTRAL_HUB_URL", "")
        token = os.environ.get("FLEET_KEY", "")
        node_name = cls.get_default_node_name()
        return {
            "enrolled": bool(hub_url and token),
            "hub_url": hub_url,
            "fleet_key": token,
            "node_name": node_name,
            "tls_verify": os.environ.get("FLEET_TLS_VERIFY", "true").lower() == "true",
            "enrolled_at": None,
        }

    @classmethod
    def save_node_config(cls, config_data: Dict[str, Any]) -> None:
        """Persist node configuration to .devctl/fleet_node.json."""
        Config.DEVCTL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        cls.CONFIG_FILE.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    @classmethod
    def enroll(
        cls,
        hub_url: str,
        token: str,
        node_name: Optional[str] = None,
        tls_verify: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Enroll this node into the Central Hub.
        Sends a test handshake to the hub's telemetry ingestion endpoint.
        If accepted, saves node credentials and configuration.
        """
        if not hub_url or not hub_url.strip():
            return {"success": False, "error": "Hub URL is required for enrollment"}
        if not token or not token.strip():
            return {"success": False, "error": "Fleet token/key is required for enrollment"}

        ingest_url, base_url = cls.normalize_hub_url(hub_url)
        name = (node_name or cls.get_default_node_name()).strip().lower()

        # Build initial enrollment telemetry payload
        from ai_ops.docker_socket import DockerSocket
        docker = DockerSocket()
        containers = docker.list_containers(all_containers=True) or []

        payload = {
            "node_name": name,
            "base_domain": Config.BASE_DOMAIN,
            "timestamp": time.time(),
            "status": "ONLINE",
            "platform": platform.platform(),
            "system": platform.system(),
            "containers_count": len(containers),
            "services_count": 0,
            "enrollment": True,
            "metrics": {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
            },
        }

        # Send test request to verify connection & authentication
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            ingest_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Fleet-Key": token.strip(),
                "X-Node-Name": name,
                "User-Agent": f"devctl-node-enroll/{name}",
            },
            method="POST",
        )

        try:
            ctx = ssl.create_default_context()
            if not tls_verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            start_t = time.time()
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                status_code = response.status
                body = response.read().decode("utf-8", errors="replace")
                latency_ms = round((time.time() - start_t) * 1000, 2)

                if status_code == 200:
                    config_data = {
                        "enrolled": True,
                        "node_name": name,
                        "hub_url": ingest_url,
                        "hub_base_url": base_url,
                        "fleet_key": token.strip(),
                        "tls_verify": tls_verify,
                        "enrolled_at": time.time(),
                        "latency_ms": latency_ms,
                    }

                    if not dry_run:
                        cls.save_node_config(config_data)

                    return {
                        "success": True,
                        "status_code": status_code,
                        "node_name": name,
                        "hub_url": ingest_url,
                        "hub_base_url": base_url,
                        "latency_ms": latency_ms,
                        "dry_run": dry_run,
                        "hub_response": json.loads(body) if body else {},
                    }
                else:
                    return {
                        "success": False,
                        "status_code": status_code,
                        "error": f"Hub responded with unexpected HTTP status {status_code}: {body}",
                    }

        except urllib.error.HTTPError as he:
            if he.code == 401 or he.code == 403:
                return {
                    "success": False,
                    "status_code": he.code,
                    "error": f"Authentication rejected by Central Hub (HTTP {he.code}). Invalid fleet token.",
                }
            return {
                "success": False,
                "status_code": he.code,
                "error": f"Hub rejected request with HTTP {he.code}: {he.reason}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unable to reach Central Hub at {ingest_url}: {e}",
            }

    @classmethod
    def get_status(cls, ping_hub: bool = True) -> Dict[str, Any]:
        """Check enrollment status and optionally test live connection to the Hub."""
        config = cls.get_node_config()
        if not config.get("enrolled") or not config.get("hub_url"):
            return {
                "enrolled": False,
                "node_name": config.get("node_name", cls.get_default_node_name()),
                "status": "NOT_ENROLLED",
                "message": "Node is not yet enrolled in any Central Hub. Run 'devctl node enroll <hub_url> --token <token>'",
            }

        status_result = {
            "enrolled": True,
            "node_name": config.get("node_name"),
            "hub_url": config.get("hub_url"),
            "hub_base_url": config.get("hub_base_url"),
            "tls_verify": config.get("tls_verify", True),
            "enrolled_at": config.get("enrolled_at"),
            "connection": "UNKNOWN",
        }

        if ping_hub:
            from ai_ops.telemetry import FleetTelemetryStreamer
            streamer = FleetTelemetryStreamer(
                hub_url=config.get("hub_url"),
                node_name=config.get("node_name"),
                fleet_key=config.get("fleet_key"),
            )
            success = streamer.send_heartbeat(handle_commands=False)
            status_result["connection"] = "CONNECTED" if success else "DISCONNECTED"

        return status_result


def cmd_node_enroll(args):
    """CLI handler for 'devctl node enroll <hub_url> --token <token>'."""
    hub_url = args.hub_url
    token = args.token or os.environ.get("FLEET_KEY")
    node_name = args.name or None
    tls_verify = not getattr(args, "insecure", False)
    dry_run = getattr(args, "dry_run", False)

    if not token:
        print("[✗] Error: --token is required. Provide the shared fleet key.")
        sys.exit(1)

    print(f"\n{'═' * 70}")
    print("🛰️  SATELLITE NODE ENROLLMENT")
    print(f"{'═' * 70}")
    print(f"• Central Hub:  {hub_url}")
    print(f"• Node Name:    {node_name or NodeManager.get_default_node_name()}")
    print(f"• TLS Verify:   {'Enabled' if tls_verify else 'Disabled (Insecure)'}")
    if dry_run:
        print("• Mode:         DRY RUN (Handshake test only)")
    print()

    print("[*] Initiating handshake with Central Hub...")
    result = NodeManager.enroll(
        hub_url=hub_url,
        token=token,
        node_name=node_name,
        tls_verify=tls_verify,
        dry_run=dry_run,
    )

    if result.get("success"):
        print(f"[✓] Handshake successful! Latency: {result.get('latency_ms')} ms")
        if not dry_run:
            print(f"[✓] Node credentials persisted to: {NodeManager.CONFIG_FILE}")
            print(f"[✓] Node '{result.get('node_name')}' is now successfully ENROLLED in Central Fleet Hub!")
        else:
            print(f"[✓] DRY RUN complete. Hub accepted credentials.")

        print("\n" + "─" * 70)
        print("💡 Next Step: Start the background telemetry agent on this node:")
        print("   devctl heartbeat")
        print("   or run container: docker compose up -d ara-agent")
        print("─" * 70 + "\n")
    else:
        print(f"[✗] Enrollment failed: {result.get('error')}")
        sys.exit(1)


def cmd_node_status(args):
    """CLI handler for 'devctl node status'."""
    skip_ping = getattr(args, "no_ping", False)
    status = NodeManager.get_status(ping_hub=not skip_ping)

    print(f"\n{'═' * 70}")
    print("🛰️  NODE FLEET STATUS")
    print(f"{'═' * 70}")
    print(f"• Node Name:      {status.get('node_name')}")
    print(f"• Enrolled:       {'YES' if status.get('enrolled') else 'NO'}")

    if not status.get("enrolled"):
        print(f"\n⚠️  {status.get('message')}\n")
        return

    print(f"• Central Hub:    {status.get('hub_url')}")
    print(f"• TLS Verify:     {'Enabled' if status.get('tls_verify') else 'Disabled'}")

    if not skip_ping:
        conn = status.get("connection")
        conn_badge = "🟢 ONLINE / CONNECTED" if conn == "CONNECTED" else "🔴 OFFLINE / UNREACHABLE"
        print(f"• Live Status:    {conn_badge}")

    print("═" * 70 + "\n")
