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
        """Register a new monitored/exposed service."""
        state = self._load_state()
        if url is None and container_type == "web" and domain:
            url = f"https://{domain}"
            
        meta = metadata or {}
        codebase = meta.get("codebase") or (meta.get("ai_inference") or {}).get("codebase") or {}

        entry = {
            "service_name": service_name,
            "container_name": container_name,
            "port": port,
            "domain": domain,
            "url": url,
            "env": env,
            "container_type": container_type,
            "workspace_dir": codebase.get("workspace_dir"),
            "compose_file": codebase.get("compose_file"),
            "git_branch": codebase.get("git_branch", "master"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": meta,
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
        """
        Scan ALL reverse proxy configs and container environments to detect real domain-to-container mappings.
        Checks:
        1. Mailcow mailcow.conf (MAILCOW_HOSTNAME) & Mailcow Nginx configs.
        2. Container mounted Caddyfiles & Nginx confs (including upstreams).
        3. Container environment variables (MAILCOW_HOSTNAME, VIRTUAL_HOST, APP_URL, DOMAIN).
        4. Docker labels (Traefik, Caddy, Virtual Host).
        5. Host /etc/nginx and /etc/caddy configs.
        Returns: dict of container_name -> {"domain": str, "source": str}
        """
        import glob
        import os
        import subprocess
        from pathlib import Path
        domains = {}  # container_name -> {"domain": ..., "source": ...}

        # 1. Scan host nginx configs
        nginx_paths = glob.glob('/etc/nginx/sites-enabled/*') + glob.glob('/etc/nginx/conf.d/*.conf')
        for conf_path in nginx_paths:
            try:
                with open(conf_path, 'r') as f:
                    content = f.read()
                server_names = re.findall(r'server_name\s+([^;]+);', content)
                proxy_passes = re.findall(r'proxy_pass\s+https?://([^:/;\s]+)', content)
                if server_names and proxy_passes:
                    domain = server_names[0].strip().split()[0]
                    upstream = proxy_passes[0].strip()
                    if domain and upstream and domain != '_':
                        domains[upstream] = {"domain": domain, "source": f"nginx:{conf_path}"}
            except Exception:
                continue

        # 2. Scan host Caddy configs
        caddy_paths = glob.glob('/etc/caddy/conf.d/*.caddy') + glob.glob('/etc/caddy/Caddyfile')
        for conf_path in caddy_paths:
            try:
                with open(conf_path, 'r') as f:
                    content = f.read()
                blocks = re.findall(r'(\S+\.\S+)\s*\{[^}]*reverse_proxy\s+(\S+)', content, re.DOTALL)
                for domain, upstream in blocks:
                    container = upstream.split(":")[0].strip()
                    if domain and container:
                        domains[container] = {"domain": domain, "source": f"caddy:{conf_path}"}
            except Exception:
                continue

        # 3. Deep Container Inspection (Env Vars, Mounts, Compose Workspaces, Labels)
        try:
            cmd = ["docker", "ps", "--format", "{{.Names}}"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
            if res.returncode == 0:
                from devctl.core.docker_mgr import DockerManager
                docker_mgr = DockerManager()
                all_container_names = [n.strip() for n in res.stdout.splitlines() if n.strip()]

                for c_name in all_container_names:
                    info = docker_mgr.inspect_container(c_name)
                    if not info:
                        continue
                    
                    config = info.get("Config", {})
                    labels = config.get("Labels", {}) or {}
                    env_vars = config.get("Env", []) or []
                    mounts = info.get("Mounts", []) or []

                    # A. Environment Variables Inspection
                    env_dict = {}
                    for e in env_vars:
                        if "=" in e:
                            k, v = e.split("=", 1)
                            env_dict[k] = v.strip()

                    # Check Mailcow hostname
                    if "MAILCOW_HOSTNAME" in env_dict and env_dict["MAILCOW_HOSTNAME"]:
                        mc_host = env_dict["MAILCOW_HOSTNAME"].strip()
                        # Assign domain to Mailcow Nginx entrypoint
                        domains[c_name] = {"domain": mc_host, "source": "env:MAILCOW_HOSTNAME"}
                        for other in all_container_names:
                            if "nginx-mailcow" in other or "sogo-mailcow" in other:
                                domains[other] = {"domain": mc_host, "source": "env:MAILCOW_HOSTNAME"}

                    # Check standard web domain environment variables
                    for d_key in ["VIRTUAL_HOST", "DOMAIN", "DOMAINS", "SERVER_NAME", "APP_DOMAIN"]:
                        if d_key in env_dict and env_dict[d_key]:
                            val = env_dict[d_key].split(",")[0].split()[0].strip()
                            if "." in val and not val.startswith("http"):
                                domains[c_name] = {"domain": val, "source": f"env:{d_key}"}

                    for u_key in ["APP_URL", "PUBLIC_URL", "NEXT_PUBLIC_APP_URL", "BASE_URL", "SITE_URL"]:
                        if u_key in env_dict and env_dict[u_key]:
                            from urllib.parse import urlparse
                            try:
                                p_url = urlparse(env_dict[u_key])
                                if p_url.hostname and "." in p_url.hostname:
                                    domains[c_name] = {"domain": p_url.hostname, "source": f"env:{u_key}"}
                            except Exception:
                                pass

                    # B. Check Docker Compose Workspace for mailcow.conf or Caddyfile
                    compose_work_dir = labels.get("com.docker.compose.project.working_dir")
                    if compose_work_dir and os.path.exists(compose_work_dir):
                        # Check mailcow.conf
                        mc_conf = Path(compose_work_dir) / "mailcow.conf"
                        if mc_conf.exists():
                            try:
                                with open(mc_conf, "r") as f:
                                    for line in f:
                                        if line.strip().startswith("MAILCOW_HOSTNAME="):
                                            mc_domain = line.strip().split("=")[1].strip()
                                            if mc_domain:
                                                if "nginx" in c_name or "sogo" in c_name or "mailcow" in c_name:
                                                    domains[c_name] = {"domain": mc_domain, "source": "mailcow.conf"}
                            except Exception:
                                pass

                        # Check Caddyfile in workspace (e.g. AniVault Caddyfile)
                        for cf_path in [Path(compose_work_dir) / "Caddyfile", Path(compose_work_dir) / "caddy" / "Caddyfile"]:
                            if cf_path.exists():
                                try:
                                    with open(cf_path, "r") as f:
                                        cf_text = f.read()
                                    # Extract domain and reverse_proxy blocks
                                    cf_blocks = re.findall(r'([a-zA-Z0-9\.\-]+(?:datakrib\.com|[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}))\s*\{([^}]+)\}', cf_text)
                                    for cf_dom, cf_body in cf_blocks:
                                        # Find reverse_proxy targets in block
                                        rp_matches = re.findall(r'reverse_proxy\s+([a-zA-Z0-9\.\-_]+)', cf_body)
                                        for rp_target in rp_matches:
                                            for target_c in all_container_names:
                                                if rp_target in target_c:
                                                    domains[target_c] = {"domain": cf_dom, "source": f"Caddyfile:{cf_path.name}"}
                                        # Also assign to the Caddy container itself
                                        if "caddy" in c_name:
                                            domains[c_name] = {"domain": cf_dom, "source": f"Caddyfile:{cf_path.name}"}
                                except Exception:
                                    pass

                    # C. Traefik & Caddy Docker labels
                    for key, val in labels.items():
                        if "traefik" in key and "rule" in key.lower() and "Host(" in val:
                            host_match = re.search(r'Host\(`([^`]+)`\)', val)
                            if host_match:
                                domains[c_name] = {"domain": host_match.group(1), "source": "traefik-label"}
                        if key == "caddy" and "." in val:
                            domains[c_name] = {"domain": val.split()[0], "source": "caddy-label"}

                    # D. Mounts inspection (mounted Nginx / Caddy config directories)
                    for mount in mounts:
                        src = mount.get("Source", "")
                        if any(kw in src.lower() for kw in ["nginx", "caddy", "apache", "mailcow"]):
                            # Scan config files in this mount
                            if os.path.isdir(src):
                                conf_files = glob.glob(f"{src}/**/*.conf", recursive=True) + glob.glob(f"{src}/**/*.caddy", recursive=True)
                                for cf in conf_files[:8]:
                                    try:
                                        with open(cf, 'r') as f:
                                            cf_content = f.read()
                                        sn = re.findall(r'server_name\s+([^;]+);', cf_content)
                                        if sn:
                                            for candidate in sn[0].split():
                                                candidate = candidate.strip()
                                                if candidate and candidate != '_' and '.' in candidate and not candidate.startswith("$"):
                                                    domains[c_name] = {"domain": candidate, "source": f"mount:{Path(cf).name}"}
                                                    break
                                    except Exception:
                                        continue
        except Exception:
            pass

        return domains

    def discover_and_index_containers(self, use_ai: bool = True, force: bool = False) -> List[Dict[str, Any]]:
        """
        Auto-discover ALL running Docker containers and register them for MONITORING.

        CRITICAL DESIGN PRINCIPLE:
        Discovery NEVER assigns wildcard staging URLs or creates Caddy routes.
        All containers are registered for health monitoring only.
        The only way to get a public wildcard URL is via `devctl expose <service> <port>`.

        This method:
        1. If force=True, flushes previous auto-discovered registrations to allow re-classification.
        2. Pre-registers ServerGuard infra containers with known URLs (dashboard -> status.BASE_DOMAIN).
        3. Detects existing real reverse proxy domains from Mailcow, Caddyfiles, Nginx, Traefik, env vars.
        4. Registers all containers for monitoring with accurate codebase workspace paths.
        """
        import subprocess
        from devctl.core.docker_mgr import DockerManager
        from devctl.core.ai_discovery import AIContainerInference

        docker_mgr = DockerManager()
        ai_engine = AIContainerInference() if use_ai else None
        state = self._load_state()
        registered = state.get("services", {})

        discovered = []

        # ── Step 0: Get all running container names ──
        try:
            cmd = ["docker", "ps", "--format", "{{.Names}}"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
            if res.returncode != 0:
                return []
            running_names = set(n.strip() for n in res.stdout.splitlines() if n.strip())
        except Exception:
            return []

        # ── Step 1: Purge stale or force-refresh auto-discovered state entries ──
        keys_to_remove = []
        for svc_key, svc_data in registered.items():
            c_name = svc_data.get("container_name", svc_key)
            # Remove if container stopped, OR if force refresh is requested
            if c_name not in running_names or force:
                keys_to_remove.append(svc_key)
        for key in keys_to_remove:
            del state["services"][key]
        if keys_to_remove:
            self._save_state(state)
            registered = state.get("services", {})

        # ── Step 2: Pre-register ServerGuard's own infrastructure ──
        SERVERGUARD_CONTAINERS = {
            "devctl-dashboard": {
                "port": 8888,
                "container_type": SERVICE_TYPE_WEB,
                "domain": f"status.{Config.BASE_DOMAIN}",
                "url": f"https://status.{Config.BASE_DOMAIN}",
                "role": "Status & Fleet Dashboard",
            },
            "caddy": {
                "port": 80,
                "container_type": SERVICE_TYPE_INFRA,
                "domain": None,
                "url": None,
                "role": "TLS Ingress & Reverse Proxy",
            },
            "ai-ops-daemon": {
                "port": 0,
                "container_type": SERVICE_TYPE_INFRA,
                "domain": None,
                "url": None,
                "role": "AI-Ops Monitoring Daemon",
            },
        }

        for sg_name, sg_info in SERVERGUARD_CONTAINERS.items():
            slug = self.sanitize_slug(sg_name)
            if sg_name in running_names:
                entry = self.register(
                    service_name=slug,
                    container_name=sg_name,
                    port=sg_info["port"],
                    domain=sg_info["domain"],
                    env="dev",
                    container_type=sg_info["container_type"],
                    url=sg_info["url"],
                    metadata={
                        "auto_discovered": True,
                        "serverguard_infra": True,
                        "ai_inference": {"role_label": sg_info["role"], "is_publicly_exposable": sg_info["url"] is not None},
                    },
                )
                discovered.append(entry)
                state = self._load_state()
                registered = state.get("services", {})

        # ── Step 3: Detect existing real domains from reverse proxies (Mailcow, Caddy, Nginx, env vars) ──
        existing_domains = self.detect_existing_domains()

        # ── Step 4: Register all remaining containers for monitoring ──
        for c_name in running_names:
            slug = self.sanitize_slug(c_name)
            if slug in registered:
                continue

            info = docker_mgr.inspect_container(c_name)
            if not info:
                continue

            state_info = info.get("State", {})
            if not state_info.get("Running", False):
                continue

            image = info.get('Config', {}).get('Image', '')
            ports = docker_mgr.detect_ports(c_name)

            # Connect container to dev-net for internal monitoring
            docker_mgr.connect_to_network(c_name)

            # AI-assisted classification and workspace inspection
            ai_profile = None
            if ai_engine:
                try:
                    ai_profile = ai_engine.inspect_and_infer(c_name)
                except Exception:
                    ai_profile = None

            # Check if this container has an existing real domain from reverse proxy detection
            real_domain_info = existing_domains.get(c_name)
            real_domain = real_domain_info["domain"] if real_domain_info else None
            real_domain_source = real_domain_info["source"] if real_domain_info else None

            # Classify container type
            if real_domain and ("nginx" in c_name or "frontend" in c_name or "web" in c_name or "sogo" in c_name):
                c_type = SERVICE_TYPE_WEB
            elif ai_profile and "database" in ai_profile.get("archetype", ""):
                c_type = SERVICE_TYPE_DATABASE
            elif ai_profile and "cache" in ai_profile.get("archetype", ""):
                c_type = SERVICE_TYPE_CACHE
            elif ai_profile and "mail" in ai_profile.get("archetype", ""):
                # If Mailcow Nginx/SOGo has a web domain, it's WEB
                c_type = SERVICE_TYPE_WEB if (real_domain and "nginx" in c_name) else SERVICE_TYPE_MAIL
            elif ai_profile and "worker" in ai_profile.get("archetype", ""):
                c_type = SERVICE_TYPE_WORKER
            elif ai_profile and "ingress" in ai_profile.get("archetype", ""):
                c_type = SERVICE_TYPE_INFRA
            else:
                c_type = self.classify_container(c_name, image, ports)

            # Determine port
            port = 0
            if ai_profile and ai_profile.get("recommended_port"):
                port = ai_profile["recommended_port"]
            elif ports:
                web_ports = [p for p in ports if p in self.WEB_PORTS]
                port = web_ports[0] if web_ports else ports[0]

            meta = {
                "auto_discovered": True,
                "detected_ports": ports,
                "image": image,
                "ai_inference": ai_profile,
            }

            # If we detected a real domain, store it in metadata
            if real_domain:
                meta["existing_domain"] = real_domain
                meta["domain_source"] = real_domain_source

            # Register for MONITORING ONLY — no wildcard URL created unless manually exposed
            entry = self.register(
                service_name=slug,
                container_name=c_name,
                port=port,
                domain=real_domain,  # Real domain if detected
                env="dev",
                container_type=c_type,
                url=f"https://{real_domain}" if real_domain else None,
                metadata=meta,
            )
            discovered.append(entry)

        return discovered
