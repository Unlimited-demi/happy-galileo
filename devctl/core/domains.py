"""
Domain & Service state management module for devctl.
Tracks exposed routes, environments, and domain mappings.
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from .config import Config, BASE_DIR

# Service type classification
SERVICE_TYPE_WEB = "web"           # Gets public URL + full monitoring
SERVICE_TYPE_API = "api"           # Backend API service
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

    @staticmethod
    def _is_valid_public_domain(candidate: str) -> bool:
        """Validate if a string is a real FQDN domain name and not a local/internal host."""
        if not candidate or len(candidate) < 4 or "." not in candidate:
            return False
        candidate = candidate.lower().strip().rstrip(".")
        # Exclude internal / reserved names
        internal_suffixes = [
            ".internal", ".local", ".localhost", ".lan", ".home", ".corp",
            ".invalid", ".example", ".test", ".arpa", ".docker", ".node"
        ]
        if any(candidate.endswith(s) for s in internal_suffixes):
            return False
        if candidate in ["localhost", "0.0.0.0", "127.0.0.1", "dev-net", "bridge", "host"]:
            return False
        # Exclude well-known vendor/documentation domains (not actual service URLs)
        vendor_domains = [
            "github.com", "github.io", "gitlab.com",
            "redis.io", "download.redis.io",
            "apache.org", "kafka.apache.org", "zookeeper.apache.org",
            "nginx.org", "caddyserver.com",
            "docker.com", "docker.io", "hub.docker.com",
            "postgresql.org", "mysql.com", "mongodb.com", "mongo.com",
            "grafana.com", "prometheus.io",
            "python.org", "pypi.org", "nodejs.org", "npmjs.com",
            "stackoverflow.com", "stackexchange.com",
            "wikipedia.org", "google.com", "microsoft.com",
            "amazon.com", "aws.amazon.com", "azure.microsoft.com",
            "cloudflare.com", "fastly.com",
        ]
        if candidate in vendor_domains:
            return False
        # Match standard FQDN (at least one dot, valid TLD of 2-24 chars)
        match = re.match(r'^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$', candidate)
        return bool(match)

    def get_running_container_names(self) -> List[str]:
        """Get running container names via Docker CLI or DockerSocket fallback."""
        import subprocess
        try:
            cmd = ["docker", "ps", "--format", "{{.Names}}"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=False)
            if res.returncode == 0:
                names = [n.strip() for n in res.stdout.splitlines() if n.strip()]
                if names:
                    return names
        except Exception:
            pass

        # Fallback to DockerSocket (for containers running python:3.11-slim)
        try:
            from ai_ops.docker_socket import DockerSocket
            ds = DockerSocket()
            containers = ds.list_containers(all_containers=False)
            names = []
            for c in containers:
                for name in c.get("Names", []):
                    clean_n = name.lstrip("/")
                    if clean_n:
                        names.append(clean_n)
            return names
        except Exception:
            return []

    def detect_existing_domains(self) -> Dict[str, Dict[str, str]]:
        """
        Universal Heuristic Domain & Reverse Proxy Resolver.
        Intelligently discovers domain-to-container routing across ANY stack without hardcoding.

        Heuristics inspected:
        1. Host Web Server Configs (Nginx, Caddy, Apache, HAProxy, Traefik).
        2. Container Mounted Web Server Configs (Caddyfile, nginx.conf, *.conf).
        3. Project Workspace Configs (*.env, *.conf, *.yaml, *.yml, *.toml, *.ini).
        4. Container Environment Signatures (*_HOSTNAME, *_DOMAIN, *_URL, VIRTUAL_HOST, etc.).
        5. Container Reverse Proxy Ingress Labels (Traefik, Caddy, Virtual Host).
        """
        import glob
        import os
        import subprocess
        from pathlib import Path
        from urllib.parse import urlparse

        domains = {}  # container_name -> {"domain": ..., "source": ...}
        all_containers = self.get_running_container_names()

        # ── 1. Host Reverse Proxy Configs (Nginx, Caddy, Apache, etc.) ──
        # Host Nginx — scan ALL possible config locations
        nginx_paths = (
            glob.glob('/etc/nginx/sites-enabled/*') +
            glob.glob('/etc/nginx/sites-available/*') +
            glob.glob('/etc/nginx/conf.d/*.conf') +
            glob.glob('/etc/nginx/nginx.conf')
        )
        for conf_path in nginx_paths:
            try:
                # Skip directories
                if not os.path.isfile(conf_path):
                    continue
                with open(conf_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # Parse each server block separately to correctly map server_name to proxy_pass
                server_blocks = re.findall(r'server\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}', content, re.DOTALL)
                for block in server_blocks:
                    server_names = re.findall(r'server_name\s+([^;]+);', block)
                    proxy_passes = re.findall(r'proxy_pass\s+https?://([^;/\s]+)', block)

                    # Map each server_name to its proxy_pass within the same block
                    for sn in server_names:
                        for d in sn.split():
                            if self._is_valid_public_domain(d):
                                for up in proxy_passes:
                                    up = up.strip()
                                    domain_info = {"domain": d.strip(), "source": f"host-nginx:{Path(conf_path).name}"}
                                    # Store by full upstream (e.g., "grafana:3000", "127.0.0.1:8080")
                                    domains[up] = domain_info
                                    # Also store by hostname/IP only (e.g., "grafana", "127.0.0.1")
                                    up_host = up.split(':')[0]
                                    domains[up_host] = domain_info
                                    # Also store by port only if present (e.g., ":3000")
                                    if ':' in up:
                                        up_port = up.split(':')[1]
                                        domains[f":{up_port}"] = domain_info
                                    for target_c in all_containers:
                                        if up_host in target_c or target_c in up_host:
                                            domains[target_c] = domain_info

                # Fallback: if no server blocks found, try flat parsing (for simple configs)
                if not server_blocks:
                    server_names = re.findall(r'server_name\s+([^;]+);', content)
                    proxy_passes = re.findall(r'proxy_pass\s+https?://([^;/\s]+)', content)
                    for sn in server_names:
                        for d in sn.split():
                            if self._is_valid_public_domain(d):
                                for up in proxy_passes:
                                    up = up.strip()
                                    domain_info = {"domain": d.strip(), "source": f"host-nginx:{Path(conf_path).name}"}
                                    domains[up] = domain_info
                                    up_host = up.split(':')[0]
                                    domains[up_host] = domain_info
                                    if ':' in up:
                                        up_port = up.split(':')[1]
                                        domains[f":{up_port}"] = domain_info
                                    for target_c in all_containers:
                                        if up_host in target_c or target_c in up_host:
                                            domains[target_c] = domain_info
            except Exception:
                continue

        # Host Caddy — scan all config locations
        caddy_paths = (
            glob.glob('/etc/caddy/conf.d/*') +
            glob.glob('/etc/caddy/Caddyfile') +
            glob.glob('/etc/caddy/*.caddy') +
            glob.glob('/opt/*/infra/Caddyfile') +
            glob.glob('/opt/*/infra/conf.d/*') +
            glob.glob('/opt/*/Caddyfile') +
            [str(BASE_DIR / "infra" / "Caddyfile")] +
            glob.glob(str(BASE_DIR / "infra" / "conf.d" / "*")) +
            glob.glob('infra/Caddyfile') +
            glob.glob('Caddyfile')
        )
        for conf_path in caddy_paths:
            try:
                # Skip directories
                if not os.path.isfile(conf_path):
                    continue
                with open(conf_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                # Parse blocks: match header { body } with multi-domain comma support
                blocks = re.findall(r'([^\r\n{}#]+)\s*\{([^}]+)\}', content)
                for header, body in blocks:
                    candidates = [d.strip() for d in re.split(r'[, \t]+', header) if d.strip()]
                    valid_domains = [d for d in candidates if self._is_valid_public_domain(d)]
                    if not valid_domains:
                        continue
                    # Prefer dedicated custom domain (e.g. ara.suburbancloud.ng over status.dev-server.datakrib.com)
                    best_domain = valid_domains[0]
                    for d in valid_domains:
                        if not d.endswith("dev-server.datakrib.com") and not d.startswith("status."):
                            best_domain = d
                            break
                        elif not d.endswith("dev-server.datakrib.com"):
                            best_domain = d

                    upstreams = re.findall(r'reverse_proxy\s+([a-zA-Z0-9\.\-_:]+)', body)
                    for up in upstreams:
                        up = up.strip()
                        domain_info = {"domain": best_domain, "all_domains": valid_domains, "source": f"host-caddy:{Path(conf_path).name}"}
                        domains[up] = domain_info
                        up_host = up.split(':')[0]
                        domains[up_host] = domain_info
                        if ':' in up:
                            up_port = up.split(':')[1]
                            domains[f":{up_port}"] = domain_info
                        for target_c in all_containers:
                            if up_host in target_c or target_c in up_host:
                                domains[target_c] = domain_info
            except Exception:
                continue

        # Host Apache — scan both sites-enabled and sites-available
        apache_paths = (
            glob.glob('/etc/apache2/sites-enabled/*.conf') +
            glob.glob('/etc/apache2/sites-available/*.conf') +
            glob.glob('/etc/httpd/conf.d/*.conf') +
            glob.glob('/etc/httpd/conf/httpd.conf')
        )
        for conf_path in apache_paths:
            try:
                # Skip directories
                if not os.path.isfile(conf_path):
                    continue
                with open(conf_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                server_names = re.findall(r'ServerName\s+([^\s]+)', content)
                server_aliases = re.findall(r'ServerAlias\s+([^\n]+)', content)
                proxy_passes = re.findall(r'ProxyPass(?:Match)?\s+[^\s]*\s+https?://([^\s]+)', content)

                all_names = server_names[:]
                for alias_line in server_aliases:
                    all_names.extend(alias_line.split())

                for d in all_names:
                    d = d.strip()
                    if self._is_valid_public_domain(d):
                        for up in proxy_passes:
                            up = up.strip().rstrip('/')
                            domain_info = {"domain": d, "source": f"host-apache:{Path(conf_path).name}"}
                            domains[up] = domain_info
                            up_host = up.split(':')[0]
                            domains[up_host] = domain_info
                            if ':' in up:
                                up_port = up.split(':')[1]
                                domains[f":{up_port}"] = domain_info
            except Exception:
                continue

        # ── 2. Universal Container Introspection ──
        try:
            all_containers = self.get_running_container_names()
            if not all_containers:
                return domains

            from devctl.core.docker_mgr import DockerManager
            docker_mgr = DockerManager()

            for c_name in all_containers:
                info = docker_mgr.inspect_container(c_name)
                if not info:
                    continue

                config = info.get("Config", {})
                labels = config.get("Labels", {}) or {}
                env_vars = config.get("Env", []) or []
                mounts = info.get("Mounts", []) or []

                # A. Container Environment Variables Inspection
                for e in env_vars:
                    if "=" not in e:
                        continue
                    k, v = e.split("=", 1)
                    k_upper = k.upper().strip()
                    v_clean = v.strip()

                    # Ignore base domain / wildcard root domain variables that do not define an individual service ingress
                    if any(term == k_upper or k_upper.endswith(f"_{term}") for term in ["BASE_DOMAIN", "DEFAULT_DOMAIN", "ROOT_DOMAIN"]):
                        continue

                    # Ignore outbound destination / client / webhook URLs (these point outwards, not inwards)
                    if any(outbound in k_upper for outbound in ["WEBHOOK", "CENTRAL_HUB", "BRAIN", "UPSTREAM", "REMOTE", "TARGET", "CLIENT", "BROKER"]):
                        continue

                    # Domain / Hostname variables
                    if any(term in k_upper for term in ["HOSTNAME", "DOMAIN", "DOMAINS", "VIRTUAL_HOST", "SERVER_NAME", "APP_HOST"]):
                        for part in v_clean.replace(";", ",").replace(" ", ",").split(","):
                            part = part.strip()
                            if self._is_valid_public_domain(part):
                                domains[c_name] = {"domain": part, "source": f"env:{k}"}

                    # URL variables (e.g. APP_URL=https://app.example.com)
                    if any(term in k_upper for term in ["APP_URL", "PUBLIC_URL", "SITE_URL", "BASE_URL", "WEB_URL", "ORIGIN"]):
                        try:
                            parsed_url = urlparse(v_clean)
                            if parsed_url.hostname and self._is_valid_public_domain(parsed_url.hostname):
                                domains[c_name] = {"domain": parsed_url.hostname, "source": f"env:{k}"}
                        except Exception:
                            pass

                # B. Docker Ingress Labels (Traefik, Caddy-Docker-Proxy, NPM, VirtualHost)
                for key, val in labels.items():
                    k_lower = key.lower()
                    if "traefik" in k_lower and "rule" in k_lower:
                        # Extract Host(`example.com`) or Host(example.com)
                        for host_match in re.findall(r'Host\([`\'"]?([^`\'")]+)[`\'"]?\)', val):
                            for h in host_match.split(","):
                                h = h.strip()
                                if self._is_valid_public_domain(h):
                                    domains[c_name] = {"domain": h, "source": "label:traefik"}

                    if "caddy" in k_lower and "." in val:
                        for token in val.split():
                            token = token.strip()
                            if self._is_valid_public_domain(token):
                                domains[c_name] = {"domain": token, "source": "label:caddy"}

                    if "virtual_host" in k_lower or "virtual.host" in k_lower:
                        for token in val.split(","):
                            token = token.strip()
                            if self._is_valid_public_domain(token):
                                domains[c_name] = {"domain": token, "source": f"label:{key}"}

                SYSTEM_PATHS = {
                    "/", "/root", "/var", "/usr", "/etc", "/proc", "/sys", "/dev",
                    "/tmp", "/bin", "/sbin", "/lib", "/lib64", "/var/lib", "/var/run",
                    "/var/log", "/var/lib/docker"
                }

                # C. Project Workspace Configuration Files
                # Check compose labels, or check bind mounts to locate workspace directory
                candidate_workspaces = []
                compose_work_dir = labels.get("com.docker.compose.project.working_dir")
                if compose_work_dir and os.path.isdir(compose_work_dir):
                    candidate_workspaces.append(Path(compose_work_dir))

                # Check bind mount parent directories
                for m in mounts:
                    if m.get("Type") == "bind":
                        src_path = Path(m.get("Source", ""))
                        if src_path.exists():
                            # Add parent dirs up to 3 levels, excluding root/system dirs
                            for p in [src_path] + list(src_path.parents)[:3]:
                                p_str = str(p).rstrip("/\\")
                                if p_str in SYSTEM_PATHS or any(p_str.startswith(sp + "/") for sp in ["/proc", "/sys", "/dev", "/var/lib/docker"]):
                                    continue
                                if p.is_dir() and any((p / f).exists() for f in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", ".env", "mailcow.conf"]):
                                    if p not in candidate_workspaces:
                                        candidate_workspaces.append(p)

                for wp in candidate_workspaces:
                    # Scan workspace config files for domain definitions
                    for conf_file in list(wp.glob("*.conf")) + list(wp.glob("*.env*")) + list(wp.glob("*Caddyfile*")) + list(wp.glob("*.yaml")) + list(wp.glob("*.yml")):
                        try:
                            with open(conf_file, "r", encoding="utf-8", errors="ignore") as f:
                                f_text = f.read()

                            # Generic Caddyfile domain blocks in workspace
                            if "Caddyfile" in conf_file.name or conf_file.suffix == ".caddy":
                                for header, body in re.findall(r'([^\r\n{}#]+)\s*\{([^}]+)\}', f_text):
                                    candidates = [d.strip() for d in re.split(r'[, \t]+', header) if d.strip()]
                                    valid_domains = [d for d in candidates if self._is_valid_public_domain(d)]
                                    if not valid_domains:
                                        continue
                                    best_domain = valid_domains[0]
                                    for d in valid_domains:
                                        if not d.endswith("dev-server.datakrib.com"):
                                            best_domain = d
                                            break

                                    domain_info = {"domain": best_domain, "all_domains": valid_domains, "source": f"workspace:{conf_file.name}"}
                                    upstreams = re.findall(r'reverse_proxy\s+([a-zA-Z0-9\.\-_:]+)', body)
                                    for up in upstreams:
                                        up = up.strip()
                                        up_host = up.split(':')[0]
                                        domains[up] = domain_info
                                        domains[up_host] = domain_info
                                        if ':' in up:
                                            up_port = up.split(':')[1]
                                            domains[f":{up_port}"] = domain_info

                            # Generic key-value configs (*.conf, *.env)
                            for line in f_text.splitlines():
                                line_clean = line.strip()
                                if "=" in line_clean and not line_clean.startswith("#"):
                                    ck, cv = line_clean.split("=", 1)
                                    ck_upper = ck.upper().strip()
                                    cv_clean = cv.strip().strip("'\"")
                                    if any(outbound in ck_upper for outbound in ["WEBHOOK", "CENTRAL_HUB", "BRAIN", "UPSTREAM", "REMOTE", "TARGET", "CLIENT", "BROKER"]):
                                        continue
                                    if any(term in ck_upper for term in ["BASE_DOMAIN", "DEFAULT_DOMAIN", "ROOT_DOMAIN"]):
                                        continue
                                    if any(term in ck_upper for term in ["HOSTNAME", "DOMAIN", "SERVER_NAME", "VIRTUAL_HOST", "APP_URL", "PUBLIC_URL", "SITE_URL", "BASE_URL", "WEB_URL"]):
                                        extracted_domain = None
                                        if "://" in cv_clean:
                                            try:
                                                h = urlparse(cv_clean).hostname
                                                if h and self._is_valid_public_domain(h):
                                                    extracted_domain = h
                                            except Exception:
                                                pass
                                        elif self._is_valid_public_domain(cv_clean):
                                            extracted_domain = cv_clean

                                        # Map project domain to web/nginx/frontend/API entrypoints in this workspace
                                        if extracted_domain:
                                            c_lower = c_name.lower()
                                            is_web_candidate = any(kw in c_lower for kw in ["nginx", "web", "frontend", "api", "sogo", "httpd", "apache", "server", "dashboard"])
                                            is_proxy = any(kw in c_lower for kw in ["caddy", "nginx-proxy", "traefik", "envoy", "haproxy"])
                                            is_strictly_internal = any(kw in c_lower for kw in ["redis", "mysql", "postgres", "memcached", "mongo", "db", "clamd", "rspamd", "watchdog", "acme", "netfilter", "unbound", "dovecot", "postfix", "ofelia", "ai-ops", "daemon"])
                                            if is_web_candidate and not is_strictly_internal and not is_proxy:
                                                domains[c_name] = {"domain": extracted_domain, "source": f"config:{conf_file.name}"}
                        except Exception:
                            continue

                # D. Container Mounted Config Directories (Nginx / Caddy / Apache / Proxy mounts)
                for mount in mounts:
                    src = mount.get("Source", "")
                    if not src or not os.path.exists(src):
                        continue
                    src_str = str(src).rstrip("/\\")
                    if src_str in SYSTEM_PATHS or any(src_str.startswith(sp + "/") for sp in ["/proc", "/sys", "/dev", "/var/lib/docker"]):
                        continue
                    if any(ignored in src_str for ignored in ["node_modules", ".git", "site-packages", "/overlay2", "/volumes"]):
                        continue

                    # If mount is a directory, scan config files shallowly (never recursive=True)
                    config_files = []
                    if os.path.isdir(src):
                        try:
                            for pat in ["*.conf", "*.caddy", "Caddyfile", "*/*.conf", "*/*.caddy", "*/Caddyfile"]:
                                config_files.extend(glob.glob(os.path.join(src, pat)))
                        except Exception:
                            pass
                    elif os.path.isfile(src):
                        if any(src.endswith(ext) for ext in [".conf", ".caddy", "Caddyfile", ".yaml", ".yml", ".env"]):
                            config_files = [src]

                    for cf in config_files[:10]:
                        try:
                            with open(cf, 'r', encoding='utf-8', errors='ignore') as f:
                                cf_content = f.read()

                            # Nginx server_name + proxy_pass
                            server_names = re.findall(r'server_name\s+([^;]+);', cf_content)
                            proxy_passes = re.findall(r'proxy_pass\s+https?://([^;/\s]+)', cf_content)
                            for sn in server_names:
                                for d in sn.split():
                                    d = d.strip()
                                    if self._is_valid_public_domain(d):
                                        domain_info = {"domain": d, "source": f"mount:{Path(cf).name}"}
                                        # Map to upstreams
                                        for up in proxy_passes:
                                            up = up.strip()
                                            domains[up] = domain_info
                                            up_host = up.split(':')[0]
                                            domains[up_host] = domain_info
                                            if ':' in up:
                                                up_port = up.split(':')[1]
                                                domains[f":{up_port}"] = domain_info
                                        # If no proxy_pass, map to the container that has this config mounted (unless it's a proxy)
                                        is_proxy = any(kw in c_name.lower() for kw in ["caddy", "nginx", "traefik", "envoy", "haproxy"])
                                        if not proxy_passes and not is_proxy:
                                            domains[c_name] = domain_info

                            # Caddyfile domain blocks
                            for header, body in re.findall(r'([^\r\n{}#]+)\s*\{([^}]+)\}', cf_content):
                                candidates = [d.strip() for d in re.split(r'[, \t]+', header) if d.strip()]
                                valid_domains = [d for d in candidates if self._is_valid_public_domain(d)]
                                if not valid_domains:
                                    continue
                                best_domain = valid_domains[0]
                                for d in valid_domains:
                                    if not d.endswith("dev-server.datakrib.com") and not d.startswith("status."):
                                        best_domain = d
                                        break
                                    elif not d.endswith("dev-server.datakrib.com"):
                                        best_domain = d

                                domain_info = {"domain": best_domain, "all_domains": valid_domains, "source": f"mount:{Path(cf).name}"}
                                # Map to upstreams in reverse_proxy directive
                                upstreams = re.findall(r'reverse_proxy\s+([a-zA-Z0-9\.\-_:]+)', body)
                                for up in upstreams:
                                    up = up.strip()
                                    domains[up] = domain_info
                                    up_host = up.split(':')[0]
                                    domains[up_host] = domain_info
                                    if ':' in up:
                                        up_port = up.split(':')[1]
                                        domains[f":{up_port}"] = domain_info
                                    # Also try to match upstream to container names
                                    for target_c in all_containers:
                                        if up_host in target_c or target_c in up_host:
                                            domains[target_c] = domain_info
                                # If no upstreams, map to the container that has this config mounted (unless it's an ingress proxy)
                                is_proxy = any(kw in c_name.lower() for kw in ["caddy", "nginx", "traefik", "envoy", "haproxy"])
                                if not upstreams and not is_proxy:
                                    domains[c_name] = domain_info
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
        running_names = set(self.get_running_container_names())
        if not running_names:
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

        # ── Step 2: Detect existing real domains from reverse proxies (Mailcow, Caddy, Nginx, env vars) ──
        existing_domains = self.detect_existing_domains()

        # Debug: print all detected domains
        if existing_domains:
            print(f"\n[DEBUG] Detected {len(existing_domains)} domain mappings:")
            for key, info in sorted(existing_domains.items()):
                print(f"  {key:30} → {info['domain']:40} (source: {info['source']})")
            print()

        # ── Step 3: Register all running containers for monitoring ──
        from ai_ops.codebase_resolver import CodebaseResolver
        resolver = CodebaseResolver()

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

            config_info = info.get("Config", {})
            labels = config_info.get("Labels") or {}
            # Exclude containers explicitly marked not to be monitored
            if str(labels.get("ara.monitor", "")).lower() == "false" or \
               str(labels.get("serverguard.monitor", "")).lower() == "false" or \
               str(labels.get("devctl.monitor", "")).lower() == "false":
                continue

            image = config_info.get('Image', '')
            ports = docker_mgr.detect_ports(c_name)

            # NOTE: We NEVER force connect foreign containers to dev-net during auto-discovery!
            # Zero network meddling contract.

            # AI-assisted classification and workspace inspection
            ai_profile = None
            if ai_engine:
                try:
                    ai_profile = ai_engine.inspect_and_infer(c_name)
                except Exception:
                    ai_profile = None

            # Resolve codebase metadata (git repo, workspace, compose file)
            codebase = resolver.resolve(c_name)

            # Check if this container is a database or cache store that must be sealed
            res_db = docker_mgr.is_database_or_cache(c_name)
            if isinstance(res_db, tuple) and len(res_db) >= 2:
                is_db, db_desc = res_db[0], res_db[1]
            else:
                is_db, db_desc = bool(res_db), ""

            if is_db:
                # DATABASE / CACHE SEALING:
                # Databases and cache containers are strictly sealed on internal networks.
                # Under NO circumstances are they assigned a public domain or ingress route.
                db_audit = docker_mgr.audit_database_security(c_name)

                # Distinguish database vs cache
                c_name_lower = c_name.lower()
                image_lower = (image or "").lower()
                if any(kw in c_name_lower or kw in image_lower for kw in ["redis", "memcached", "valkey", "dragonfly", "keydb"]):
                    c_type = SERVICE_TYPE_CACHE
                else:
                    c_type = SERVICE_TYPE_DATABASE

                port = ports[0] if ports else 0
                public_domain = None
                public_url = None

                meta = {
                    "auto_discovered": True,
                    "detected_ports": ports,
                    "image": image,
                    "ai_inference": ai_profile or {
                        "role_label": f"Internal Sealed {db_desc}",
                        "is_publicly_exposable": False,
                        "archetype": "database" if c_type == SERVICE_TYPE_DATABASE else "cache",
                    },
                    "codebase": codebase,
                    "sealed_database": True,
                    "publicly_exposable": False,
                    "security_audit": db_audit,
                }
            else:
                # Check if this container has an existing real domain from reverse proxy detection
                # Try multiple lookup strategies: container name, compose service, container:port, :port, fuzzy match, container IP
                real_domain_info = None
                real_domain = None
                real_domain_source = None

                # Strategy 1: Exact container name match
                if c_name in existing_domains:
                    real_domain_info = existing_domains[c_name]

                # Strategy 1b: Docker Compose service name match (e.g., "dashboard" for "devctl-dashboard")
                if not real_domain_info:
                    compose_svc = labels.get("com.docker.compose.service")
                    if compose_svc and compose_svc in existing_domains:
                        real_domain_info = existing_domains[compose_svc]
                    elif compose_svc and ports:
                        for p in ports:
                            key = f"{compose_svc}:{p}"
                            if key in existing_domains:
                                real_domain_info = existing_domains[key]
                                break

                # Strategy 2: Container name with port (e.g., "grafana:3000")
                if not real_domain_info and ports:
                    for p in ports:
                        key = f"{c_name}:{p}"
                        if key in existing_domains:
                            real_domain_info = existing_domains[key]
                            break

                # Strategy 3: Port only (e.g., ":3000", ":8888")
                if not real_domain_info and ports:
                    for p in ports:
                        key = f":{p}"
                        if key in existing_domains:
                            real_domain_info = existing_domains[key]
                            break

                # Strategy 4: Upstream substring or fuzzy match
                if not real_domain_info:
                    for up_k, dinfo in existing_domains.items():
                        if not up_k.startswith(":") and len(up_k) >= 3:
                            up_host = up_k.split(":")[0].lower()
                            c_lower = c_name.lower()
                            if up_host and (up_host in c_lower or c_lower in up_host):
                                real_domain_info = dinfo
                                break

                # Strategy 5: Container IP address (inspect container network)
                if not real_domain_info:
                    try:
                        net_info = info.get("NetworkSettings", {}).get("Networks", {})
                        for net_name, net_data in net_info.items():
                            ip_addr = net_data.get("IPAddress")
                            if ip_addr and ip_addr in existing_domains:
                                real_domain_info = existing_domains[ip_addr]
                                break
                            # Also try IP:port
                            if ip_addr and ports:
                                for p in ports:
                                    key = f"{ip_addr}:{p}"
                                    if key in existing_domains:
                                        real_domain_info = existing_domains[key]
                                        break
                                if real_domain_info:
                                    break
                    except Exception:
                        pass

                if real_domain_info:
                    real_domain = real_domain_info.get("domain")
                    real_domain_source = real_domain_info.get("source")
                    # Debug: print where the domain was detected from
                    print(f"  [DEBUG] {c_name}: {real_domain} (from {real_domain_source})")

                # Classify container type
                if real_domain and ("nginx" in c_name or "frontend" in c_name or "web" in c_name or "sogo" in c_name or "dashboard" in c_name):
                    c_type = SERVICE_TYPE_WEB
                elif any(proxy_kw in c_name.lower() for proxy_kw in ["caddy", "ingress", "traefik"]):
                    c_type = SERVICE_TYPE_INFRA
                elif any(daemon_kw in c_name.lower() for daemon_kw in ["ai-ops", "daemon"]):
                    c_type = SERVICE_TYPE_INFRA
                elif any(brain_kw in c_name.lower() for brain_kw in ["brain", "ollama"]):
                    c_type = SERVICE_TYPE_API
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
                    "codebase": codebase,
                }

                # If we detected a real domain from nginx/Caddy/Apache, use it!
                if real_domain:
                    meta["existing_domain"] = real_domain
                    meta["domain_source"] = real_domain_source
                    # Set the public URL and domain so users see what's actually exposed
                    public_domain = real_domain
                    public_url = f"https://{real_domain}"
                else:
                    # No existing domain detected — register for monitoring only
                    public_url = None
                    public_domain = None

            entry = self.register(
                service_name=slug,
                container_name=c_name,
                port=port,
                domain=public_domain,
                env="dev",
                container_type=c_type,
                url=public_url,
                metadata=meta,
            )
            discovered.append(entry)

        return discovered
