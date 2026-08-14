"""
Domain & Service state management module for devctl.
Tracks exposed routes, environments, and domain mappings.
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from .config import Config


class DomainRegistry:
    """Manages active domain allocations and persistent state."""

    def __init__(self, state_file=None):
        self.state_file = state_file or Config.STATE_FILE

    def _load_state(self) -> Dict[str, Any]:
        """Load state from JSON file with legacy fallback."""
        state = {"services": {}, "updated_at": None}
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                state = {"services": {}, "updated_at": None}

        # If empty, check legacy state locations and migrate
        if not state.get("services"):
            from pathlib import Path
            legacy_paths = [
                Path("/root/.devctl/state.json"),
                Path.home() / ".devctl" / "state.json",
                Path("/home/oldroot/.devctl/state.json"),
            ]
            for leg in legacy_paths:
                if leg.exists() and leg != self.state_file:
                    try:
                        with open(leg, "r", encoding="utf-8") as f:
                            leg_data = json.load(f)
                            if leg_data.get("services"):
                                state["services"] = leg_data["services"]
                                self._save_state(state)
                                break
                    except Exception:
                        pass
        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save state atomically to JSON file."""
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_file = self.state_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            temp_file.replace(self.state_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    @staticmethod
    def sanitize_slug(name: str) -> str:
        """Sanitize a name to make it a valid DNS subdomain label."""
        name = name.lower().strip()
        name = re.sub(r"[^a-z0-9\-]", "-", name)
        name = re.sub(r"-+", "-", name).strip("-")
        return name or "service"

    def register(
        self,
        service_name: str,
        container_name: str,
        port: int,
        domain: str,
        env: str = "dev",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register a new exposed service."""
        state = self._load_state()
        entry = {
            "service_name": service_name,
            "container_name": container_name,
            "port": port,
            "domain": domain,
            "url": f"https://{domain}",
            "env": env,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
            "status": "active",
        }
        state["services"][service_name] = entry
        self._save_state(state)
        return entry

    def unregister(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Remove a service from registry."""
        state = self._load_state()
        entry = state["services"].pop(service_name, None)
        if entry:
            self._save_state(state)
        return entry

    def get_service(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Get service details."""
        state = self._load_state()
        return state["services"].get(service_name)

    def get_by_domain(self, domain: str) -> Optional[Dict[str, Any]]:
        """Lookup service by domain."""
        state = self._load_state()
        for svc in state["services"].values():
            if svc.get("domain") == domain:
                return svc
        return None

    def list_services(self) -> List[Dict[str, Any]]:
        """List all registered services."""
        state = self._load_state()
        return list(state["services"].values())

    def discover_and_index_containers(self) -> List[Dict[str, Any]]:
        """
        Auto-discover running Docker containers on the machine,
        index their ports and locations, assign them domain routes,
        and make them immediately monitorable by AI-Ops.
        """
        import subprocess
        from devctl.core.docker_mgr import DockerManager
        from devctl.core.caddy import CaddyManager

        docker_mgr = DockerManager()
        caddy_mgr = CaddyManager()
        state = self._load_state()
        registered = state.get("services", {})

        # System/infra and internal mail daemon containers to skip from auto-web-exposing
        skip_exact = {"caddy", "ai-ops-daemon", "devctl-dashboard"}
        skip_keywords = ["dovecot", "postfix", "rspamd", "clamd", "unbound", "netfilter", "php-fpm", "acme-mailcow", "solr-mailcow", "dockerapi-mailcow"]
        discovered = []

        try:
            # Query all running containers via docker inspect
            cmd = ["docker", "ps", "--format", "{{.Names}}"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
            if res.returncode != 0:
                return []

            container_names = [n.strip() for n in res.stdout.splitlines() if n.strip()]

            for c_name in container_names:
                c_lower = c_name.lower()
                if c_name in skip_exact or c_name in registered:
                    continue
                if any(kw in c_lower for kw in skip_keywords):
                    continue

                info = docker_mgr.inspect_container(c_name)
                if not info:
                    continue

                state_info = info.get("State", {})
                if not state_info.get("Running", False):
                    continue

                # Detect exposed ports
                ports = docker_mgr.detect_ports(c_name)
                # Filter internal/DB ports unless it's an app port
                app_ports = [p for p in ports if p not in [5432, 6379, 27017, 3306]]
                port = app_ports[0] if app_ports else (ports[0] if ports else 80)

                # Connect container to dev-net if not already connected
                docker_mgr.connect_to_network(c_name)

                # Auto-generate domain and route
                slug = self.sanitize_slug(c_name)
                domain = Config.get_full_domain(slug, "dev")

                # Register in state
                entry = self.register(
                    service_name=slug,
                    container_name=c_name,
                    port=port,
                    domain=domain,
                    env="dev",
                    metadata={"auto_discovered": True, "detected_ports": ports},
                )

                # Add dynamic Caddy route & SSL
                caddy_mgr.add_route(domain=domain, upstream_host=c_name, upstream_port=port)
                discovered.append(entry)

        except Exception as e:
            print(f"[!] Discovery error: {e}")
            pass

        return discovered
