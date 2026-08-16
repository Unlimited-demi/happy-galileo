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
from devctl.core.auth import AuthManager

STATIC_DIR = Path(__file__).parent / "static"
FLEET_STORE = {}


class DashboardHandler(SimpleHTTPRequestHandler):
    """Multi-threaded HTTP Request handler serving static UI and REST API."""

    def _check_auth(self, auth_type='dashboard'):
        """Check authentication. Returns True if authorized."""
        try:
            auth_mgr = AuthManager()
            if auth_type == 'telemetry':
                key = self.headers.get('X-Fleet-Key', '')
                return auth_mgr.validate_telemetry_key(key)
            else:
                auth_header = self.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    key = auth_header[7:]
                    return auth_mgr.validate_dashboard_key(key)
                return not auth_mgr._load_auth().get('initialized', False)  # Allow if not yet set up
        except Exception:
            return True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    # Explicit MIME map — prevents system mimetypes from returning text/html for .js
    MIME_OVERRIDES = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
    }

    def guess_type(self, path):
        """Override to guarantee correct MIME types for static assets."""
        import posixpath
        _, ext = posixpath.splitext(path)
        if ext.lower() in self.MIME_OVERRIDES:
            return self.MIME_OVERRIDES[ext.lower()]
        return super().guess_type(path)

    def end_headers(self):
        """Prevent aggressive browser caching during development and updates."""
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    @staticmethod
    def _json_serialize(obj):
        """Fallback serializer for Path, datetime, and custom objects."""
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2, default=self._json_serialize).encode("utf-8")
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

            # Strip /static/ prefix for backward compatibility — files live
            # directly in the static directory so /static/app.js → /app.js
            if path.startswith("/static/"):
                self.path = path[len("/static"):] + ("?" + parsed.query if parsed.query else "")
                path = self.path.split("?")[0]

            if path.startswith("/api/") and path != "/api/ask":
                if not self._check_auth(auth_type='dashboard'):
                    self._send_json({"error": "Unauthorized"}, status=401)
                    return

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

                services = registry.list_services() or []
                incidents = bus.list_incidents(only_open=True) or []

                # Query Docker containers quickly via DockerSocket
                containers = docker.list_containers(all_containers=True) or []
                container_map = {}
                for c in containers:
                    if not isinstance(c, dict):
                        continue
                    c_img = c.get("Image", "unknown") or "unknown"
                    v_tag = c_img.split(":")[-1] if ":" in c_img else "latest"
                    for n in (c.get("Names") or []):
                        clean_n = n.lstrip("/")
                        container_map[clean_n] = {
                            "image": c_img,
                            "version": v_tag,
                            "status": c.get("Status", "RUNNING") or "RUNNING",
                            "state": c.get("State", "running") or "running",
                            "id": str(c.get("Id", "") or "")[:12],
                        }

                # Merge service info with container versions
                merged_services = []
                for svc in services:
                    if not isinstance(svc, dict):
                        continue
                    name = svc.get("service_name", "app") or "app"
                    c_name = svc.get("container_name", name) or name
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
                local_incidents = bus.list_incidents(only_open=only_open) or []

                # Tag local incidents with their source node
                local_node_name = os.environ.get("NODE_NAME", "vm-01 (Primary)")
                for inc in local_incidents:
                    if isinstance(inc, dict):
                        inc["source_node"] = local_node_name

                # Merge incidents from all remote fleet nodes safely
                all_incidents = [inc for inc in local_incidents if isinstance(inc, dict)]
                for node_name, node_data in list(FLEET_STORE.items()):
                    if not isinstance(node_data, dict) or node_name == local_node_name:
                        continue
                    remote_incidents = node_data.get("all_incidents") or node_data.get("open_incidents") or []
                    if isinstance(remote_incidents, list):
                        for rinc in remote_incidents:
                            if isinstance(rinc, dict):
                                r_copy = dict(rinc)
                                r_copy["source_node"] = node_name
                                if only_open and r_copy.get("state") in ["RESOLVED", "CLOSED", "VERIFIED"]:
                                    continue
                                all_incidents.append(r_copy)

                # Sort newest first safely
                all_incidents.sort(key=lambda x: str(x.get("created_at", "") or ""), reverse=True)
                self._send_json({"incidents": all_incidents})
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
                    services = registry.list_services() or []
                    containers = docker.list_containers(all_containers=True) or []
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

                nodes_list = []
                current_time = time.time()
                for k, n in list(FLEET_STORE.items()):
                    if isinstance(n, dict):
                        n_copy = dict(n)
                        # Mark offline if no heartbeat in 90 seconds
                        n_copy["online"] = (current_time - float(n_copy.get("timestamp", 0) or 0)) < 90
                        nodes_list.append(n_copy)

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

            elif path.startswith("/api/incidents/") and path.endswith("/worker-logs"):
                # Extract inc_id: /api/incidents/<id>/worker-logs
                inc_id = path[len("/api/incidents/"): -len("/worker-logs")].strip("/")
                if inc_id:
                    from ai_ops.dispatcher import IncidentDispatcher
                    status_info = IncidentDispatcher.get_worker_status(inc_id)
                    self._send_json(status_info)
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
            import traceback
            traceback.print_exc()
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/telemetry/ingest":
                if not self._check_auth(auth_type='telemetry'):
                    self._send_json({"error": "Unauthorized"}, status=401)
                    return

                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body else {}
                node_name = payload.get("node_name", "unknown")
                payload["received_at"] = time.time()
                payload["client_ip"] = self.client_address[0]
                FLEET_STORE[node_name] = payload
                self._send_json({"status": "received", "node": node_name})
                return

            elif path.startswith("/api/incidents/") and path.endswith("/dispatch"):
                # Extract incident_id: /api/incidents/<id>/dispatch
                inc_id = path[len("/api/incidents/"): -len("/dispatch")].strip("/")
                if inc_id:
                    from ai_ops.dispatcher import IncidentDispatcher
                    dispatcher = IncidentDispatcher()
                    result = dispatcher.dispatch(inc_id, fleet_store=FLEET_STORE)
                    self._send_json(result, status=200 if result.get("success") else 400)
                    return

            elif path == "/api/incidents/purge":
                bus = IncidentBus()
                deleted = 0
                if bus.incidents_dir.exists():
                    for f in list(bus.incidents_dir.glob("*.json")) + list(bus.incidents_dir.glob("*.md")):
                        try:
                            f.unlink()
                            deleted += 1
                        except Exception:
                            pass
                self._send_json({"status": "purged", "deleted_files": deleted})
                return

            self.send_error(404, "Endpoint not found")
        except Exception as e:
            import traceback
            traceback.print_exc()
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
