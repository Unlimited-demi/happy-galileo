"""
Status & Ops Web Dashboard Backend.
Lightweight API server for inspecting services, health status, Playwright screenshots,
and Incident dossiers directly from your phone or browser.
"""

import json
import os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from devctl.core.docker_mgr import DockerManager
from devctl.core.incident_bus import IncidentBus
from ai_ops.health_checker import HealthChecker

STATIC_DIR = Path(__file__).parent / "static"


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP Request handler serving static UI and REST API."""

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
        parsed = urlparse(self.path)
        path = parsed.path

        # Caddy On-Demand TLS Permission Verification
        if path == "/api/ask":
            params = parse_qs(parsed.query)
            domain = params.get("domain", [""])[0].lower()
            # Allow any domain ending with our base domain (e.g. dev-server.datakrib.com)
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
            checker = HealthChecker()
            registry = DomainRegistry()
            bus = IncidentBus()

            services = registry.list_services()
            health_results = checker.check_all_services()
            incidents = bus.list_incidents(only_open=True)

            # Query Docker Engine API via Unix socket directly
            # (python:3.11-slim doesn't have the docker CLI binary)
            total_containers = 0
            try:
                import http.client
                conn = http.client.HTTPConnection("localhost")
                conn.sock = __import__('socket').socket(
                    __import__('socket').AF_UNIX, __import__('socket').SOCK_STREAM
                )
                conn.sock.connect("/var/run/docker.sock")
                conn.request("GET", "/containers/json")
                resp = conn.getresponse()
                if resp.status == 200:
                    container_data = json.loads(resp.read().decode())
                    total_containers = len(container_data)
                conn.close()
            except Exception:
                total_containers = 0

            # Merge service info with latest health probe
            merged_services = []
            health_map = {h["service_name"]: h for h in health_results}

            for svc in services:
                name = svc["service_name"]
                h_info = health_map.get(name, {})
                merged = {**svc, **h_info}
                merged_services.append(merged)

            self._send_json({
                "base_domain": Config.BASE_DOMAIN,
                "network": Config.DOCKER_NETWORK,
                "services": merged_services,
                "open_incidents_count": len(incidents),
                "total_containers": total_containers,
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


def run_dashboard(port: int = Config.DASHBOARD_PORT, host: str = Config.DASHBOARD_HOST):
    """Start the dashboard HTTP server."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"🚀 AI-Ops & Dev Status Dashboard running at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Dashboard stopped.")
        httpd.server_close()


if __name__ == "__main__":
    run_dashboard()
