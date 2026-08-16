"""
Docker Socket Client for AI-Ops containers.
Queries the Docker Engine API directly via /var/run/docker.sock
since python:3.11-slim does not ship the docker CLI binary.
"""

import http.client
import json
import socket as _socket
from typing import Dict, List, Any, Optional


class DockerSocketError(Exception):
    pass


class DockerSocket:
    """Lightweight Docker Engine API client over Unix socket."""

    SOCK_PATH = "/var/run/docker.sock"

    def _request(self, method: str, path: str, body: Optional[bytes] = None) -> Any:
        """Send an HTTP request through the Docker Unix socket."""
        conn = http.client.HTTPConnection("localhost")
        try:
            sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            sock.connect(self.SOCK_PATH)
            conn.sock = sock
            headers = {"Content-Type": "application/json"} if body else {}
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read().decode("utf-8", errors="replace")
            if resp.status >= 400:
                return None
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ── Container Operations ──

    def list_containers(self, all_containers: bool = False) -> List[Dict[str, Any]]:
        """List running containers (or all if all_containers=True)."""
        path = "/containers/json"
        if all_containers:
            path += "?all=true"
        result = self._request("GET", path)
        return result if isinstance(result, list) else []

    def inspect_container(self, name_or_id: str) -> Optional[Dict[str, Any]]:
        """Inspect a container by name or ID."""
        result = self._request("GET", f"/containers/{name_or_id}/json")
        return result if isinstance(result, dict) else None

    def get_logs(self, name_or_id: str, tail: int = 100) -> str:
        """Fetch recent container logs."""
        result = self._request(
            "GET",
            f"/containers/{name_or_id}/logs?stdout=true&stderr=true&tail={tail}"
        )
        if result is None:
            return ""
        if isinstance(result, str):
            # Docker multiplexed log stream has 8-byte header frames per chunk.
            # Header format: [stream_type(1), 0, 0, 0, size(4)] where stream_type is 1=stdout, 2=stderr
            # Only strip when the first byte matches Docker stream magic bytes.
            lines = []
            for line in result.split("\n"):
                raw = line.encode("utf-8", errors="replace")
                if len(raw) > 8 and raw[0] in (0, 1, 2) and raw[1] == 0 and raw[2] == 0 and raw[3] == 0:
                    # This is a Docker multiplexed stream frame — strip the 8-byte header
                    cleaned = raw[8:]
                else:
                    # Plain text log line — keep as-is
                    cleaned = raw
                decoded = cleaned.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    lines.append(decoded)
            return "\n".join(lines)
        return str(result)

    def restart_container(self, name_or_id: str, timeout: int = 10) -> bool:
        """Restart a container."""
        result = self._request("POST", f"/containers/{name_or_id}/restart?t={timeout}")
        # Docker returns 204 No Content on success (result will be empty string)
        return result is not None

    def is_running(self, name_or_id: str) -> bool:
        """Check if a container is running."""
        info = self.inspect_container(name_or_id)
        if not info:
            return False
        return info.get("State", {}).get("Running", False)

    def get_restart_count(self, name_or_id: str) -> int:
        """Get the number of times a container has been restarted."""
        info = self.inspect_container(name_or_id)
        if not info:
            return 0
        return info.get("RestartCount", 0)

    def connect_to_network(self, container: str, network: str) -> bool:
        """Connect a container to a Docker network."""
        body = json.dumps({"Container": container}).encode()
        result = self._request("POST", f"/networks/{network}/connect", body=body)
        return result is not None
