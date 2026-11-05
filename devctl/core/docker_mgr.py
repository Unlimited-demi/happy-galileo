"""
Docker Manager module for devctl.
Handles container lifecycle, internal network enforcement (dev-net),
port detection, security auditing (zero public host ports), and container inspection.
"""

import json
import subprocess
from typing import Dict, List, Any, Optional, Tuple
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
        if create["success"]:
            return True
        # Fallback to DockerSocket (e.g. inside python:3.11-slim container)
        try:
            from ai_ops.docker_socket import DockerSocket
            ds = DockerSocket()
            net = ds._request("GET", f"/networks/{self.network_name}")
            if isinstance(net, dict) and "Id" in net:
                return True
            created = ds._request("POST", "/networks/create", body=json.dumps({"Name": self.network_name, "Driver": "bridge"}).encode())
            return isinstance(created, dict) and "Id" in created
        except Exception:
            return False

    def inspect_container(self, container_name_or_id: str) -> Optional[Dict[str, Any]]:
        """Inspect a Docker container and return structured JSON."""
        res = self._run_docker(["inspect", container_name_or_id])
        if res["success"] and res["stdout"]:
            try:
                data = json.loads(res["stdout"])
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
            except Exception:
                pass
        # Fallback to DockerSocket if docker CLI is absent or failed
        try:
            from ai_ops.docker_socket import DockerSocket
            ds = DockerSocket()
            return ds.inspect_container(container_name_or_id)
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
        if res["success"]:
            return True
        # Fallback to DockerSocket
        try:
            from ai_ops.docker_socket import DockerSocket
            return DockerSocket().connect_to_network(container_name, self.network_name)
        except Exception:
            return False

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

    DATABASE_PORT_MAP = {
        5432: "PostgreSQL",
        6379: "Redis",
        3306: "MySQL/MariaDB",
        27017: "MongoDB",
        11211: "Memcached",
        9200: "Elasticsearch",
        9042: "Cassandra",
        26257: "CockroachDB",
        8123: "ClickHouse",
    }
    DATABASE_KEYWORDS = [
        "postgres", "mysql", "mariadb", "mongo", "redis", "memcached",
        "elasticsearch", "cassandra", "cockroach", "clickhouse", "timescale",
        "valkey", "dragonfly", "keydb"
    ]

    def is_database_or_cache(self, container_name: str) -> Tuple[bool, str]:
        """
        Check if a container is a database or cache store that must be sealed.
        Returns (is_db, description).
        """
        info = self.inspect_container(container_name)
        if not info:
            c_lower = container_name.lower()
            for kw in self.DATABASE_KEYWORDS:
                if kw in c_lower:
                    return True, f"database/cache service matching '{kw}'"
            return False, ""

        config = info.get("Config", {})
        image_lower = (config.get("Image") or "").lower()
        name_lower = container_name.lower()

        # Check image and container name
        for kw in self.DATABASE_KEYWORDS:
            if kw in image_lower or kw in name_lower:
                return True, f"database/cache engine ({kw})"

        # Check exposed ports
        ports = self.detect_ports(container_name)
        for p in ports:
            if p in self.DATABASE_PORT_MAP:
                return True, f"{self.DATABASE_PORT_MAP[p]} database/cache (port {p})"

        return False, ""

    def audit_database_security(self, container_name: str) -> Dict[str, Any]:
        """
        Audit database / cache container for exposure and password protection.
        Ensures databases are sealed on internal networks with strong auth.
        """
        is_db, db_desc = self.is_database_or_cache(container_name)
        if not is_db:
            return {"is_database": False, "violations": [], "safe": True}

        info = self.inspect_container(container_name) or {}
        config = info.get("Config", {})
        env_vars = config.get("Env") or []
        env_dict = {}
        for e in env_vars:
            if "=" in e:
                k, v = e.split("=", 1)
                env_dict[k] = v

        raw_cmd = config.get("Cmd") or []
        if isinstance(raw_cmd, str):
            raw_cmd = [raw_cmd]
        cmd_str = " ".join(raw_cmd)

        violations = []
        warnings = []

        # 1. Host Port Exposure Check (Must not be bound to 0.0.0.0 or host interfaces)
        ports = info.get("NetworkSettings", {}).get("Ports") or {}
        for port_key, bindings in ports.items():
            if bindings:
                for binding in bindings:
                    host_ip = binding.get("HostIp", "")
                    host_port = binding.get("HostPort", "")
                    if host_ip in ["0.0.0.0", "::", ""]:
                        violations.append(
                            f"CRITICAL: Database port {port_key} is publicly published to 0.0.0.0:{host_port}! "
                            f"Databases must be sealed inside Docker networks with ZERO host port exposure."
                        )
                    elif host_ip:
                        warnings.append(
                            f"Database port {port_key} is bound to host IP {host_ip}:{host_port}."
                        )

        # 2. Password & Authentication Checks
        image_lower = (config.get("Image") or "").lower()
        name_lower = container_name.lower()

        # Redis Authentication Check
        if "redis" in image_lower or "redis" in name_lower or any(p in ports for p in ["6379/tcp", "6379/udp"]):
            has_requirepass = "--requirepass" in cmd_str or "requirepass" in cmd_str
            has_env_pass = any(k in env_dict for k in ["REDIS_PASSWORD", "REDIS_PASSWORD_FILE", "REDISCLI_AUTH"])
            if not has_requirepass and not has_env_pass:
                violations.append(
                    "CRITICAL: Redis container is running without password authentication ('requirepass')! "
                    "Unauthenticated Redis allows arbitrary remote execution."
                )

        # PostgreSQL Authentication Check
        if "postgres" in image_lower or "postgres" in name_lower or any(p in ports for p in ["5432/tcp", "5432/udp"]):
            auth_method = env_dict.get("POSTGRES_HOST_AUTH_METHOD", "").lower()
            has_pass = bool(env_dict.get("POSTGRES_PASSWORD") or env_dict.get("POSTGRES_PASSWORD_FILE"))
            if auth_method == "trust":
                violations.append(
                    "CRITICAL: PostgreSQL is configured with 'POSTGRES_HOST_AUTH_METHOD=trust'! "
                    "Anyone on the network can connect without credentials."
                )
            elif not has_pass:
                violations.append(
                    "CRITICAL: PostgreSQL container is missing POSTGRES_PASSWORD! "
                    "A strong database password must be configured."
                )

        # MySQL / MariaDB Authentication Check
        if any(kw in image_lower or kw in name_lower for kw in ["mysql", "mariadb"]):
            allow_empty = env_dict.get("MYSQL_ALLOW_EMPTY_PASSWORD", "").lower() in ["yes", "true", "1"]
            has_root_pass = bool(env_dict.get("MYSQL_ROOT_PASSWORD") or env_dict.get("MARIADB_ROOT_PASSWORD"))
            if allow_empty or not has_root_pass:
                violations.append(
                    "CRITICAL: MySQL/MariaDB container has empty or unconfigured root password!"
                )

        # MongoDB Authentication Check
        if "mongo" in image_lower or "mongo" in name_lower:
            has_mongo_pass = bool(env_dict.get("MONGO_INITDB_ROOT_PASSWORD"))
            has_auth_flag = "--auth" in cmd_str
            if not has_mongo_pass and not has_auth_flag:
                violations.append(
                    "CRITICAL: MongoDB container is running without authentication enabled!"
                )

        return {
            "is_database": True,
            "description": db_desc,
            "container_name": container_name,
            "violations": violations,
            "warnings": warnings,
            "safe": len(violations) == 0,
        }

    def list_containers(self, only_running: bool = True) -> List[Dict[str, Any]]:
        """List containers with detailed metadata."""
        args = ["ps", "--format", "{{json .}}"]
        if not only_running:
            args.append("-a")

        res = self._run_docker(args)
        if res["success"] and res["stdout"]:
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
            if containers:
                return containers

        # Fallback to DockerSocket
        try:
            from ai_ops.docker_socket import DockerSocket
            ds = DockerSocket()
            raw_containers = ds.list_containers(all_containers=not only_running)
            containers = []
            for c in raw_containers:
                names = [n.lstrip("/") for n in c.get("Names", [])]
                name = names[0] if names else c.get("Id", "")[:12]
                containers.append({
                    "ID": c.get("Id", "")[:12],
                    "Names": name,
                    "Image": c.get("Image", ""),
                    "Status": c.get("Status", ""),
                    "State": c.get("State", ""),
                })
            return containers
        except Exception:
            return []

    def get_logs(self, container_name: str, tail: int = 100) -> str:
        """Fetch recent container logs."""
        res = self._run_docker(["logs", "--tail", str(tail), container_name])
        if res["success"] and (res["stdout"] or res["stderr"]):
            return res["stdout"] or res["stderr"]
        try:
            from ai_ops.docker_socket import DockerSocket
            return DockerSocket().get_logs(container_name, tail=tail)
        except Exception:
            return res.get("stderr", "")

    def restart_container(self, container_name: str) -> bool:
        """Restart a container safely."""
        res = self._run_docker(["restart", container_name])
        if res["success"]:
            return True
        try:
            from ai_ops.docker_socket import DockerSocket
            return DockerSocket().restart_container(container_name)
        except Exception:
            return False

    def is_running(self, container_name: str) -> bool:
        """Check if container is running."""
        info = self.inspect_container(container_name)
        if not info:
            return False
        return info.get("State", {}).get("Running", False)
