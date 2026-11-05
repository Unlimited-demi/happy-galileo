"""
Status & Ops Web Dashboard Backend.
Lightweight multi-threaded API server for inspecting services, health status,
Playwright screenshots, and Incident dossiers directly from your phone or browser.
"""

import json
import os
import time
import secrets
import subprocess
import shutil
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from devctl.core.incident_bus import IncidentBus
from devctl.core.fleet_store import FleetStore, NodeStatus
from ai_ops.docker_socket import DockerSocket
from devctl.core.auth import (
    AuthManager,
    ROLE_VIEWER,
    ROLE_OPERATOR,
    ROLE_APPROVER,
    ROLE_ADMIN,
)
from ai_ops.job_signer import JobSigner

STATIC_DIR = Path(__file__).parent / "static"
FLEET_STORE = FleetStore()
ALLOWED_NODE_ACTIONS = {"restart_container", "resync_network", "purge_incidents"}


class DashboardHandler(SimpleHTTPRequestHandler):
    """Multi-threaded HTTP Request handler serving static UI and REST API with RBAC."""

    def _get_request_role(self) -> Optional[str]:
        """Extract and return authenticated RBAC role. Fails closed (returns None)."""
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            key = auth_header[7:].strip()
            auth_mgr = AuthManager()
            return auth_mgr.get_role_for_key(key)
        return None

    def _require_role(self, required_role: str) -> bool:
        """Enforce RBAC role requirement. Sends 401/403 and returns False if unauthorized."""
        role = self._get_request_role()
        if not role:
            self._send_json({"error": "Unauthorized: Authentication required"}, status=401)
            return False
        if not AuthManager.has_permission(role, required_role):
            self._send_json({
                "error": f"Forbidden: Insufficient permissions (requires role '{required_role}', your role is '{role}')",
                "required_role": required_role,
                "current_role": role,
            }, status=403)
            return False
        return True

    def _check_auth(self, auth_type='dashboard'):
        """Check authentication. Returns True if authorized. Fails closed."""
        try:
            auth_mgr = AuthManager()
            if auth_type == 'telemetry':
                key = self.headers.get('X-Fleet-Key', '')
                fleet_key_env = os.environ.get('FLEET_KEY', '')
                if fleet_key_env and key and secrets.compare_digest(fleet_key_env, key):
                    return True
                return auth_mgr.validate_telemetry_key(key)
            else:
                return self._get_request_role() is not None
        except Exception:
            return False

    def __init__(self, *args, directory=None, **kwargs):
        if directory is None:
            dist_dir = Path(__file__).resolve().parent / "dist"
            frontend_dist = Path(__file__).resolve().parent / "frontend" / "dist"
            static_dir = Path(__file__).resolve().parent / "static"
            if frontend_dist.exists() and (frontend_dist / "index.html").exists():
                directory = str(frontend_dist)
            elif dist_dir.exists() and (dist_dir / "index.html").exists():
                directory = str(dist_dir)
            else:
                directory = str(static_dir)
        super().__init__(*args, directory=str(directory), **kwargs)

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
                if not self._require_role(ROLE_VIEWER):
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
                        "status_code": svc.get("status_code", None),
                        "response_time_ms": svc.get("response_time_ms", None),
                        "image": c_info.get("image", svc.get("image", "app:latest")),
                        "version": c_info.get("version", "latest"),
                        "container_status": c_info.get("status") or ("RUNNING" if is_running else "STOPPED"),
                        "container_id": c_info.get("id", ""),
                    }
                    merged_services.append(merged)

                # Auto-register local node into FLEET_STORE
                # Auto-register local node into FLEET_STORE
                local_node_name = os.environ.get("NODE_NAME", "vm-01 (Primary)")
                client_ip = self.client_address[0] if hasattr(self, "client_address") and self.client_address else "127.0.0.1"
                FLEET_STORE.upsert_node({
                    "node_name": local_node_name,
                    "base_domain": Config.BASE_DOMAIN,
                    "containers_count": len(containers),
                    "services_count": len(merged_services),
                    "services": merged_services,
                    "open_incidents_count": len(incidents),
                }, client_ip=client_ip)

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
                for node_data in FLEET_STORE.get_all_nodes():
                    if not isinstance(node_data, dict):
                        continue
                    node_name = node_data.get("node_name")
                    if not node_name or node_name == local_node_name:
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

            elif path.startswith("/api/incidents/") and path.endswith("/worker-logs"):
                # Extract inc_id: /api/incidents/<id>/worker-logs
                inc_id = path[len("/api/incidents/"): -len("/worker-logs")].strip("/")
                if inc_id:
                    from ai_ops.dispatcher import IncidentDispatcher
                    status_info = IncidentDispatcher.get_worker_status(inc_id)
                    self._send_json(status_info)
                    return

            elif path.startswith("/api/incidents/"):
                inc_id = path[len("/api/incidents/"):].strip("/")
                bus = IncidentBus()
                inc = bus.get_incident(inc_id)
                
                # If not found locally, search connected satellite nodes in FLEET_STORE
                if not inc:
                    for node_data in FLEET_STORE.get_all_nodes():
                        if isinstance(node_data, dict):
                            for rinc in (node_data.get("all_incidents") or node_data.get("open_incidents") or []):
                                if isinstance(rinc, dict) and rinc.get("id") == inc_id:
                                    inc = dict(rinc)
                                    break
                        if inc:
                            break

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

            elif path == "/api/metrics":
                # Time-series metrics & degradation trends recorded by the AI-Ops daemon.
                # /api/metrics                     → trend summary for all services
                # /api/metrics?service=X&hours=2   → raw sample history for one service
                from ai_ops.metrics_store import MetricsStore
                qs = parse_qs(parsed.query)
                service = (qs.get("service") or [""])[0]
                hours = float((qs.get("hours") or ["2"])[0])
                store = MetricsStore()
                try:
                    if service:
                        self._send_json({
                            "service": service,
                            "hours": hours,
                            "samples": store.history(service, hours=hours),
                            "trends": store.detect_trends(service, window_hours=hours),
                        })
                    else:
                        self._send_json({
                            "services": store.services(),
                            "trends": store.trend_summary(Config.TREND_WINDOW_HOURS),
                        })
                finally:
                    store.close()
                return

            elif path == "/api/fleet/commands":
                history = FLEET_STORE.get_command_history(limit=50)
                self._send_json({
                    "history": history,
                    "results": history,
                    "allowed_actions": sorted(ALLOWED_NODE_ACTIONS),
                })
                return

            elif path == "/api/fleet/nodes":
                # Ensure local node is always populated
                local_node_name = os.environ.get("NODE_NAME", "vm-01 (Primary)")
                if not FLEET_STORE.get_node(local_node_name):
                    registry = DomainRegistry()
                    docker = DockerSocket()
                    bus = IncidentBus()
                    services = registry.list_services() or []
                    containers = docker.list_containers(all_containers=True) or []
                    client_ip = self.client_address[0] if hasattr(self, "client_address") and self.client_address else "127.0.0.1"
                    FLEET_STORE.upsert_node({
                        "node_name": local_node_name,
                        "base_domain": Config.BASE_DOMAIN,
                        "containers_count": len(containers),
                        "services_count": len(services),
                        "services": services,
                        "open_incidents_count": len(bus.list_incidents(only_open=True)),
                    }, client_ip=client_ip)

                nodes_list = FLEET_STORE.get_all_nodes()
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
            elif path.startswith("/api/terminals/") and path.endswith("/stream"):
                # SSE Terminal Stream: /api/terminals/<session>/stream
                session_name = path[len("/api/terminals/"): -len("/stream")].strip("/")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                # Ensure session exists: auto-spawn if not present
                has_sess = subprocess.run(["tmux", "has-session", "-t", session_name], capture_output=True)
                if has_sess.returncode != 0:
                    target_cwd = "/app" if os.path.isdir("/app") else "."
                    subprocess.run(["tmux", "new-session", "-d", "-s", session_name, "-c", target_cwd, "bash"], check=False)
                    welcome = f'echo "=== [ARA WORKER CONSOLE: {session_name}] ==="; echo "Physical Workspace: $(pwd)"; echo "Agent Status: Ready (Type commands or run: opencode)"; echo ""'
                    subprocess.run(["tmux", "send-keys", "-t", session_name, welcome, "C-m"], check=False)

                last_output = None
                try:
                    for _ in range(60): # Stream for 30s before client auto-reconnects
                        capture = subprocess.run(["tmux", "capture-pane", "-e", "-p", "-t", session_name], capture_output=True, text=True)
                        output = capture.stdout if capture.returncode == 0 else f"[Tmux session '{session_name}' initialized]\r\n"
                        
                        if output != last_output:
                            last_output = output
                            msg = f"data: {json.dumps({'output': output, 'session': session_name})}\n\n"
                            self.wfile.write(msg.encode("utf-8"))
                            self.wfile.flush()
                        time.sleep(0.4)
                except (BrokenPipeError, ConnectionResetError):
                    pass
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

            # Strictly require authentication on ALL API POST routes
            if path == "/api/telemetry/ingest":
                if not self._check_auth(auth_type='telemetry'):
                    self._send_json({"error": "Unauthorized telemetry key"}, status=401)
                    return
            elif path.startswith("/api/"):
                if not self._check_auth(auth_type='dashboard'):
                    self._send_json({"error": "Unauthorized dashboard access"}, status=401)
                    return

            # Explicitly reject remote shell input endpoints (Zero RCE Surface)
            if path.startswith("/api/terminals/") and (path.endswith("/input") or path.endswith("/resize")):
                self._send_json({
                    "error": "Terminal keystroke input and remote execution are permanently disabled for security.",
                    "status": "disabled"
                }, status=403)
                return

            if path == "/api/telemetry/ingest":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body else {}
                node_name = payload.get("node_name", "unknown")
                client_ip = self.client_address[0] if hasattr(self, "client_address") and self.client_address else "127.0.0.1"

                # Persist node heartbeat in fleet store
                FLEET_STORE.upsert_node(payload, client_ip=client_ip)

                # Record command results reported back by the node
                cmd_results = payload.get("command_results", [])
                if cmd_results and isinstance(cmd_results, list):
                    FLEET_STORE.record_command_results(node_name, cmd_results)

                # Deliver (and drain) any pending commands queued for this node, cryptographically signed
                pending = FLEET_STORE.drain_pending_commands(node_name)
                fleet_key = os.environ.get("FLEET_KEY", "default-fleet-key")
                signed_pending = [JobSigner.sign_command(cmd, fleet_key) for cmd in pending]
                self._send_json({
                    "status": "received",
                    "node": node_name,
                    "pending_commands": signed_pending,
                })
                return

            elif path == "/api/fleet/command":
                # Queue a whitelisted infra command for a sub-node. Requires OPERATOR role or above.
                if not self._require_role(ROLE_OPERATOR):
                    return
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body else {}
                node = payload.get("node", "")
                action = payload.get("action", "")
                target = payload.get("target", "")

                if action not in ALLOWED_NODE_ACTIONS:
                    self._send_json({
                        "error": f"Action '{action}' not allowed",
                        "allowed": sorted(ALLOWED_NODE_ACTIONS),
                    }, status=400)
                    return
                if not node:
                    self._send_json({"error": "Missing 'node'"}, status=400)
                    return

                command = FLEET_STORE.queue_command(node_name=node, action=action, target=target)
                self._send_json({"status": "queued", "node": node, "command": command})
                return

            elif path == "/api/fleet/nodes/prune":
                # Requires ADMIN role
                if not self._require_role(ROLE_ADMIN):
                    return
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body else {}
                max_age = float(payload.get("max_age_seconds", 3600))
                deleted = FLEET_STORE.prune_offline_nodes(max_age_seconds=max_age)
                self._send_json({"status": "pruned", "deleted_nodes": deleted})
                return

            elif path.startswith("/api/incidents/") and path.endswith("/dispatch"):
                # Requires APPROVER role or above
                if not self._require_role(ROLE_APPROVER):
                    return
                inc_id = path[len("/api/incidents/"): -len("/dispatch")].strip("/")
                if inc_id:
                    from ai_ops.dispatcher import IncidentDispatcher
                    dispatcher = IncidentDispatcher()
                    result = dispatcher.dispatch(inc_id, fleet_store=FLEET_STORE)
                    self._send_json(result, status=200 if result.get("success") else 400)
                    return

            elif path == "/api/chatops/query":
                # ChatOps endpoint for Concert (@ARA mentions)
                wh_secret = self.headers.get("X-Webhook-Secret", "")
                expected_secret = os.environ.get("CONCERT_WEBHOOK_SECRET", "")
                is_valid_wh = expected_secret and wh_secret and secrets.compare_digest(expected_secret, wh_secret)

                if not is_valid_wh and not self._require_role(ROLE_OPERATOR):
                    return

                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
                payload = json.loads(body) if body else {}
                query_text = payload.get("query", "")

                from ai_ops.brain import BrainEngine
                brain = BrainEngine()
                chatops_result = brain.handle_chatops_query(
                    query=query_text,
                    thread_context=payload,
                    fleet_store=FLEET_STORE
                )
                self._send_json(chatops_result)
                return

            elif path == "/api/incidents/purge":
                # Requires ADMIN role
                if not self._require_role(ROLE_ADMIN):
                    return
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
    dist_dir = Path(__file__).resolve().parent / "dist"
    static_dir = Path(__file__).resolve().parent / "static"
    serve_dir = str(dist_dir) if dist_dir.exists() and (dist_dir / "index.html").exists() else str(static_dir)

    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, DashboardHandler)
    print(f"🚀 AI-Ops & Multi-Server Fleet Dashboard serving from '{serve_dir}' at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Dashboard stopped.")
        httpd.server_close()


if __name__ == "__main__":
    run_dashboard()

