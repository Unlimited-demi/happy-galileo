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
    """Lightweight Docker Engine API client over Unix socket with connection reuse."""

    SOCK_PATH = "/var/run/docker.sock"

    def __init__(self):
        self._conn: Optional[http.client.HTTPConnection] = None
        self._lock = __import__("threading").Lock()

    def _get_conn(self) -> http.client.HTTPConnection:
        """Return a reusable HTTP connection over the Docker Unix socket."""
        if self._conn is not None:
            return self._conn
        conn = http.client.HTTPConnection("localhost")
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.connect(self.SOCK_PATH)
        conn.sock = sock
        self._conn = conn
        return conn

    def _request(self, method: str, path: str, body: Optional[bytes] = None) -> Any:
        """Send an HTTP request through the Docker Unix socket."""
        with self._lock:
            try:
                conn = self._get_conn()
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
                # Connection may be stale — tear down and retry once
                self._close_conn()
                try:
                    conn = self._get_conn()
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
                    self._close_conn()
                    return None

    def _close_conn(self):
        """Tear down the persistent connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def close(self):
        """Public close method."""
        self._close_conn()

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

    def get_networks(self, name_or_id: str) -> List[str]:
        """List the Docker networks a container is attached to."""
        info = self.inspect_container(name_or_id)
        if not info:
            return []
        networks = info.get("NetworkSettings", {}).get("Networks", {}) or {}
        return list(networks.keys())

    def stats_container(self, name_or_id: str) -> Optional[Dict[str, Any]]:
        """
        One-shot resource stats snapshot (no streaming).
        Returns {"mem_bytes", "mem_limit", "cpu_pct"} or None.
        """
        raw = self._request("GET", f"/containers/{name_or_id}/stats?stream=false")
        if not isinstance(raw, dict):
            return None
        try:
            mem = raw.get("memory_stats", {}) or {}
            mem_usage = mem.get("usage")
            mem_limit = mem.get("limit")
            # Exclude page cache where the kernel reports it (cgroup v1/v2)
            cache = (mem.get("stats", {}) or {}).get("inactive_file", 0) or 0
            if mem_usage is not None:
                mem_usage = max(0, mem_usage - cache)

            cpu_pct = None
            cpu = raw.get("cpu_stats", {}) or {}
            precpu = raw.get("precpu_stats", {}) or {}
            cpu_delta = (cpu.get("cpu_usage", {}).get("total_usage", 0) or 0) - \
                        (precpu.get("cpu_usage", {}).get("total_usage", 0) or 0)
            sys_delta = (cpu.get("system_cpu_usage", 0) or 0) - (precpu.get("system_cpu_usage", 0) or 0)
            if cpu_delta > 0 and sys_delta > 0:
                online_cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", []) or [1])
                cpu_pct = (cpu_delta / sys_delta) * online_cpus * 100.0

            return {"mem_bytes": mem_usage, "mem_limit": mem_limit, "cpu_pct": cpu_pct}
        except Exception:
            return None

    def exec_in_container(self, name_or_id: str, cmd: List[str]) -> bool:
        """
        Run a command inside a container via the Docker Engine exec API
        (no docker CLI needed). Returns True if the command exited 0.
        """
        body = json.dumps({"AttachStdout": True, "AttachStderr": True, "Cmd": cmd}).encode()
        created = self._request("POST", f"/containers/{name_or_id}/exec", body=body)
        if not isinstance(created, dict) or "Id" not in created:
            return False
        exec_id = created["Id"]
        self._request("POST", f"/exec/{exec_id}/start", body=json.dumps({"Detach": False, "Tty": False}).encode())
        inspect = self._request("GET", f"/exec/{exec_id}/json")
        return isinstance(inspect, dict) and inspect.get("ExitCode") == 0
