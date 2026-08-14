"""
Status & Ops Web Dashboard Backend.
Lightweight multi-threaded API server for inspecting services, health status,
Playwright screenshots, and Incident dossiers directly from your phone or browser.
"""

import json
import os
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from devctl.core.incident_bus import IncidentBus
from ai_ops.docker_socket import DockerSocket

STATIC_DIR = Path(__file__).parent / "static"
FLEET_STORE = {}


class DashboardHandler(SimpleHTTPRequestHandler):
    """Multi-threaded HTTP Request handler serving static UI and REST API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            # Caddy On-Demand TLS Permission Verification
            if path == "/api/ask":
                params = parse_qs(parsed.query)
                domain = params.get("domain", [""])[0].lower()
                if domain.endswith(Config.BASE_DOMAIN):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Forbidden Domain")
                return

            # API Endpoints
            if path == "/api/status":
                registry = DomainRegistry()
                bus = IncidentBus()
                docker = DockerSocket()

                services = registry.list_services()
                incidents = bus.list_incidents(only_open=True)

                # Query Docker containers quickly via DockerSocket
                containers = docker.list_containers(all_containers=True)
                container_map = {}
                for c in containers:
                    c_img = c.get("Image", "unknown")
                    v_tag = c_img.split(":")[-1] if ":" in c_img else "latest"
                    for n in c.get("Names", []):
                        clean_n = n.lstrip("/")
                        container_map[clean_n] = {
                            "image": c_img,
                            "version": v_tag,
                            "status": c.get("Status", "RUNNING"),
                            "state": c.get("State", "running"),
                            "id": c.get("Id", "")[:12],
                        }

                # Merge service info with container versions
                merged_services = []
                for svc in services:
                    name = svc.get("service_name", "app")
                    c_name = svc.get("container_name", name)
                    c_info = container_map.get(c_name, {})
                    is_running = c_info.get("state") == "running"
                    merged = {
                        **svc,
                        "healthy": is_running,
                        "status_code": 200 if is_running else 503,
                        "response_time_ms": 15 if is_running else 0,
                        "image": c_info.get("image", svc.get("image", "app:latest")),
                        "version": c_info.get("version", "latest"),
                        "container_status": c_info.get("status", "RUNNING" if is_running else "STOPPED"),
                        "container_id": c_info.get("id", ""),
                    }
                    merged_services.append(merged)

                # Auto-register local node into FLEET_STORE
                local_node_name = os.environ.get("NODE_NAME", "vm-01 (Primary)")
                FLEET_STORE[local_node_name] = {
                    "node_name": local_node_name,
                    "base_domain": Config.BASE_DOMAIN,
                    "timestamp": time.time(),
                    "status": "ONLINE",
                    "containers_count": len(containers),
                    "services_count": len(merged_services),
                    "services": merged_services,
                    "open_incidents_count": len(incidents),
                    "online": True,
                }

                self._send_json({
                    "node_name": local_node_name,
                    "base_domain": Config.BASE_DOMAIN,
                    "network": Config.DOCKER_NETWORK,
                    "services": merged_services,
                    "open_incidents_count": len(incidents),
                    "total_containers": len(containers),
                })
                return

            elif path == "/api/incidents":
                bus = IncidentBus()
                params = parse_qs(parsed.query)
                only_open = params.get("all", ["true"])[0] != "true"
                incidents = bus.list_incidents(only_open=only_open)
                self._send_json({"incidents": incidents})
                return

            elif path.startswith("/api/incidents/"):
                inc_id = path[len("/api/incidents/"):]
                bus = IncidentBus()
                inc = bus.get_incident(inc_id)
                if not inc:
                    self._send_json({"error": "Incident not found"}, status=404)
                    return
                md_path = bus.incidents_dir / f"{inc_id}.md"
                md_text = ""
                if md_path.exists():
                    try:
                        md_text = md_path.read_text(encoding="utf-8")
                    except Exception:
                        pass
                inc["markdown_dossier"] = md_text
                self._send_json({"incident": inc})
                return

            elif path == "/api/fleet/nodes":
                # Ensure local node is always populated
                local_node_name = os.environ.get("NODE_NAME", "vm-01 (Primary)")
                if local_node_name not in FLEET_STORE:
                    registry = DomainRegistry()
                    docker = DockerSocket()
                    bus = IncidentBus()
                    services = registry.list_services()
                    containers = docker.list_containers(all_containers=True)
                    FLEET_STORE[local_node_name] = {
                        "node_name": local_node_name,
                        "base_domain": Config.BASE_DOMAIN,
                        "timestamp": time.time(),
                        "status": "ONLINE",
                        "containers_count": len(containers),
                        "services_count": len(services),
                        "services": services,
                        "open_incidents_count": len(bus.list_incidents(only_open=True)),
                        "online": True,
                    }

                nodes_list = list(FLEET_STORE.values())
                current_time = time.time()
                for n in nodes_list:
                    # Mark offline if no heartbeat in 90 seconds
                    n["online"] = (current_time - n.get("timestamp", 0)) < 90
                self._send_json({"nodes": nodes_list, "total_nodes": len(nodes_list)})
                return

            elif path == "/api/screenshots":
                screenshots = []
                if Config.SCREENSHOTS_DIR.exists():
                    for svc_dir in Config.SCREENSHOTS_DIR.iterdir():
                        if svc_dir.is_dir():
                            svc_name = svc_dir.name
                            for img in svc_dir.glob("*.png"):
                                screenshots.append({
                                    "service_name": svc_name,
                                    "type": img.stem,
                                    "file_name": img.name,
                                    "url_path": f"/screenshots/{svc_name}/{img.name}",
                                })
                self._send_json({"screenshots": screenshots})
                return

            # Serve screenshots directory dynamically
            elif path.startswith("/screenshots/"):
                rel_path = path[len("/screenshots/"):]
                file_path = Config.SCREENSHOTS_DIR / rel_path
                if file_path.exists() and file_path.is_file():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(file_path.stat().st_size))
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        self.wfile.write(f.read())
                    return
                else:
                    self.send_error(404, "Screenshot not found")
                    return

            # Serve static assets
            super().do_GET()

        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/telemetry/ingest":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body)
                node_name = payload.get("node_name", "unknown")
                payload["received_at"] = time.time()
                payload["client_ip"] = self.client_address[0]
                FLEET_STORE[node_name] = payload
                self._send_json({"status": "received", "node": node_name})
                return

            self.send_error(404, "Endpoint not found")
        except Exception as e:
            self._send_json({"error": str(e)}, status=400)


def run_dashboard(port: int = Config.DASHBOARD_PORT, host: str = Config.DASHBOARD_HOST):
    """Start the multi-threaded dashboard HTTP server."""
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, DashboardHandler)
    print(f"🚀 AI-Ops & Multi-Server Fleet Dashboard running at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Dashboard stopped.")
        httpd.server_close()


if __name__ == "__main__":
    run_dashboard()
