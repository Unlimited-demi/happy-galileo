"""
Domain & Service state management module for devctl.
Tracks exposed routes, environments, and domain mappings.
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from .config import Config

# Service type classification
SERVICE_TYPE_WEB = "web"           # Gets public URL + full monitoring
SERVICE_TYPE_DATABASE = "database"  # Monitored only, no public URL
SERVICE_TYPE_CACHE = "cache"        # Monitored only, no public URL
SERVICE_TYPE_MAIL = "mail"          # Monitored only, no public URL
SERVICE_TYPE_INFRA = "infra"        # Monitored only, no public URL
SERVICE_TYPE_WORKER = "worker"      # Monitored only, no public URL


class DomainRegistry:
    """Manages active domain allocations and persistent state."""

    # Known non-web ports
    NON_WEB_PORTS = {3306, 5432, 6379, 11211, 27017, 5672, 15672, 25, 110, 143, 465, 587, 993, 995, 4190, 9200, 9300}

    # Known web ports
    WEB_PORTS = {80, 443, 3000, 4000, 5000, 8000, 8080, 8443, 8888, 9090, 4200, 5173}

    # Image/name keywords for classification
    DB_KEYWORDS = {"postgres", "mysql", "mariadb", "mongo", "mongodb", "cockroach", "timescale", "influxdb", "clickhouse"}
    CACHE_KEYWORDS = {"redis", "memcached", "valkey", "dragonfly", "keydb"}
    MAIL_KEYWORDS = {"dovecot", "postfix", "rspamd", "clamd", "olefy", "sogo", "mailcow", "watchdog-mailcow", "acme-mailcow", "ofelia-mailcow", "unbound", "netfilter", "php-fpm"}
    INFRA_KEYWORDS = {"caddy", "traefik", "nginx-proxy", "haproxy", "ai-ops-daemon", "devctl-dashboard", "certbot", "letsencrypt"}
    WORKER_KEYWORDS = {"ofelia", "celery", "sidekiq", "cron", "worker", "scheduler", "dockerize", "certdumper", "solr"}

    @staticmethod
    def classify_container(container_name, image, ports):
        """Classify a container into a service type based on image, name, and ports."""
        name_lower = container_name.lower()
        image_lower = (image or "").lower()
        combined = f"{name_lower} {image_lower}"
        
        # Check keywords in order of specificity
        for kw in DomainRegistry.INFRA_KEYWORDS:
            if kw in combined:
                return SERVICE_TYPE_INFRA
        for kw in DomainRegistry.MAIL_KEYWORDS:
            if kw in combined:
                return SERVICE_TYPE_MAIL
        for kw in DomainRegistry.DB_KEYWORDS:
            if kw in combined:
                return SERVICE_TYPE_DATABASE
        for kw in DomainRegistry.CACHE_KEYWORDS:
            if kw in combined:
                return SERVICE_TYPE_CACHE
        for kw in DomainRegistry.WORKER_KEYWORDS:
            if kw in combined:
                return SERVICE_TYPE_WORKER
        
        # Check ports: if ALL ports are non-web, classify as infra
        if ports and all(p in DomainRegistry.NON_WEB_PORTS for p in ports):
            return SERVICE_TYPE_DATABASE  # Generic non-web
        
        # Default: it's a web service
        return SERVICE_TYPE_WEB

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
        container_type: str = "web",
        url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Register a new exposed service."""
        state = self._load_state()
        if url is None and container_type == "web" and domain:
            url = f"https://{domain}"
            
        entry = {
            "service_name": service_name,
            "container_name": container_name,
            "port": port,
            "domain": domain,
            "url": url,
            "env": env,
            "container_type": container_type,
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

    def detect_existing_domains(self):
        """Scan existing reverse proxy configs to detect real domain-to-container mappings."""
        import glob, re
        domains = {}  # container_name -> domain
        
        # Scan nginx configs
        nginx_paths = glob.glob('/etc/nginx/sites-enabled/*') + glob.glob('/etc/nginx/conf.d/*.conf')
        for conf_path in nginx_paths:
            try:
                with open(conf_path, 'r') as f:
                    content = f.read()
                # Extract server_name and proxy_pass pairs
                server_names = re.findall(r'server_name\s+([^;]+);', content)
                proxy_passes = re.findall(r'proxy_pass\s+https?://([^:/;\s]+)', content)
                if server_names and proxy_passes:
                    domain = server_names[0].strip().split()[0]
                    upstream = proxy_passes[0].strip()
                    if domain and upstream and domain != '_':
                        domains[upstream] = domain
            except Exception:
                continue
        
        return domains

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

        discovered = []
        
        # Detect existing real domains
        existing_domains = self.detect_existing_domains()

        try:
            # Query all running containers via docker inspect
            cmd = ["docker", "ps", "--format", "{{.Names}}"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
            if res.returncode != 0:
                return []

            container_names = [n.strip() for n in res.stdout.splitlines() if n.strip()]

            for c_name in container_names:
                if c_name in registered:
                    continue

                info = docker_mgr.inspect_container(c_name)
                if not info:
                    continue

                state_info = info.get("State", {})
                if not state_info.get("Running", False):
                    continue

                image = info.get('Config', {}).get('Image', '')

                # Detect exposed ports
                ports = docker_mgr.detect_ports(c_name)

                # Connect container to dev-net if not already connected
                docker_mgr.connect_to_network(c_name)
                
                # Classify the container
                c_type = self.classify_container(c_name, image, ports)

                slug = self.sanitize_slug(c_name)
                domain = existing_domains.get(c_name) or Config.get_full_domain(slug, "dev")

                if c_type == SERVICE_TYPE_WEB:
                    # Pick port from WEB_PORTS intersection, or first port
                    web_ports_intersection = [p for p in ports if p in self.WEB_PORTS]
                    port = web_ports_intersection[0] if web_ports_intersection else (ports[0] if ports else 80)
                    
                    # Register in state
                    entry = self.register(
                        service_name=slug,
                        container_name=c_name,
                        port=port,
                        domain=domain,
                        env="dev",
                        container_type=c_type,
                        metadata={"auto_discovered": True, "detected_ports": ports},
                    )

                    # Add dynamic Caddy route & SSL
                    caddy_mgr.add_route(domain=domain, upstream_host=c_name, upstream_port=port)
                    discovered.append(entry)
                else:
                    # Non-web container
                    port = ports[0] if ports else 0
                    
                    # Register in state with no url
                    entry = self.register(
                        service_name=slug,
                        container_name=c_name,
                        port=port,
                        domain=domain,
                        env="dev",
                        container_type=c_type,
                        url=None,
                        metadata={"auto_discovered": True, "detected_ports": ports},
                    )
                    discovered.append(entry)

        except Exception as e:
            print(f"[!] Discovery error: {e}")
            pass

        return discovered
