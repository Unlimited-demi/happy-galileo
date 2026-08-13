"""
Docker Manager module for devctl.
Handles container lifecycle, internal network enforcement (dev-net),
port detection, security auditing (zero public host ports), and container inspection.
"""

import json
import subprocess
from typing import Dict, List, Any, Optional
from .config import Config


class DockerManager:
    """Manages Docker containers and enforces security policies."""

    def __init__(self, network_name: Optional[str] = None):
        self.network_name = network_name or Config.DOCKER_NETWORK

    def _run_docker(self, args: List[str]) -> Dict[str, Any]:
        """Execute a Docker CLI command securely."""
        cmd = ["docker"] + args
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            return {
                "success": res.returncode == 0,
                "returncode": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
            }
        except FileNotFoundError:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "docker executable not found in PATH",
            }
        except Exception as e:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
            }

    def ensure_network(self) -> bool:
        """Ensure the internal Docker bridge network exists."""
        check = self._run_docker(["network", "inspect", self.network_name])
        if check["success"]:
            return True
        create = self._run_docker(["network", "create", self.network_name])
        return create["success"]

    def inspect_container(self, container_name_or_id: str) -> Optional[Dict[str, Any]]:
        """Inspect a Docker container and return structured JSON."""
        res = self._run_docker(["inspect", container_name_or_id])
        if not res["success"] or not res["stdout"]:
            return None
        try:
            data = json.loads(res["stdout"])
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return None
        except Exception:
            return None

    def connect_to_network(self, container_name: str) -> bool:
        """Connect a container to the internal dev-net if not already attached."""
        self.ensure_network()
        info = self.inspect_container(container_name)
        if not info:
            return False

        networks = info.get("NetworkSettings", {}).get("Networks", {})
        if self.network_name in networks:
            return True

        res = self._run_docker(["network", "connect", self.network_name, container_name])
        return res["success"]

    def detect_ports(self, container_name: str) -> List[int]:
        """Detect open/exposed internal ports for a container."""
        info = self.inspect_container(container_name)
        if not info:
            return []

        ports = []
        # Check Config.ExposedPorts
        exposed = info.get("Config", {}).get("ExposedPorts") or {}
        for port_proto in exposed.keys():
            port_num = port_proto.split("/")[0]
            if port_num.isdigit():
                ports.append(int(port_num))

        # Check NetworkSettings.Ports
        net_ports = info.get("NetworkSettings", {}).get("Ports") or {}
        for port_proto in net_ports.keys():
            port_num = port_proto.split("/")[0]
            if port_num.isdigit() and int(port_num) not in ports:
                ports.append(int(port_num))

        return ports

    def audit_security(self, container_name: str) -> Dict[str, Any]:
        """
        Audit container for direct host port exposure.
        Returns warning if container is exposing public ports like 0.0.0.0:3000.
        """
        info = self.inspect_container(container_name)
        if not info:
            return {"exists": False, "safe": False, "violations": ["Container not found"]}

        violations = []
        ports = info.get("NetworkSettings", {}).get("Ports") or {}
        for port_key, bindings in ports.items():
            if bindings:
                for binding in bindings:
                    host_ip = binding.get("HostIp", "")
                    host_port = binding.get("HostPort", "")
                    if host_ip in ["0.0.0.0", "::", ""]:
                        violations.append(
                            f"Port {port_key} is publicly published to host port {host_port} on {host_ip or 'all interfaces'}."
                        )

        networks = info.get("NetworkSettings", {}).get("Networks", {})
        has_dev_net = self.network_name in networks

        return {
            "exists": True,
            "container_name": container_name,
            "connected_to_dev_net": has_dev_net,
            "has_public_ports": len(violations) > 0,
            "violations": violations,
            "safe": len(violations) == 0 and has_dev_net,
        }

    def list_containers(self, only_running: bool = True) -> List[Dict[str, Any]]:
        """List containers with detailed metadata."""
        args = ["ps", "--format", "{{json .}}"]
        if not only_running:
            args.append("-a")

        res = self._run_docker(args)
        if not res["success"] or not res["stdout"]:
            return []

        containers = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c_data = json.loads(line)
                containers.append(c_data)
            except Exception:
                pass
        return containers

    def get_logs(self, container_name: str, tail: int = 100) -> str:
        """Fetch recent container logs."""
        res = self._run_docker(["logs", "--tail", str(tail), container_name])
        return res["stdout"] or res["stderr"]

    def restart_container(self, container_name: str) -> bool:
        """Restart a container safely."""
        res = self._run_docker(["restart", container_name])
        return res["success"]

    def is_running(self, container_name: str) -> bool:
        """Check if container is running."""
        info = self.inspect_container(container_name)
        if not info:
            return False
        return info.get("State", {}).get("Running", False)
