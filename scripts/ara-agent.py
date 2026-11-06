#!/usr/bin/env python3
"""
ARA Autonomous Node Telemetry & Log Agent
Lightweight, zero-dependency Python 3 agent that streams server metrics,
container states, ingress routing, git metadata, and live container logs
to the ARA Central Hub over outbound HTTPS.

Designed for production satellite nodes (zero inbound open ports required).
"""

import os
import sys
import time
import json
import gzip
import socket
import http.client
import urllib.request
import urllib.error
import subprocess
import re
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


class DockerSocket:
    """Zero-dependency Docker Engine API client via /var/run/docker.sock."""

    SOCK_PATH = "/var/run/docker.sock"

    def __init__(self):
        self._conn = None

    def is_available(self) -> bool:
        return os.path.exists(self.SOCK_PATH) and os.access(self.SOCK_PATH, os.R_OK)

    def _get_conn(self) -> http.client.HTTPConnection:
        if self._conn is not None:
            return self._conn
        conn = http.client.HTTPConnection("localhost")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.SOCK_PATH)
        conn.sock = sock
        self._conn = conn
        return conn

    def _request(self, method: str, path: str, raw: bool = False) -> Any:
        try:
            conn = self._get_conn()
            conn.request(method, path)
            resp = conn.getresponse()
            data = resp.read()
            if resp.status >= 400:
                return None
            if raw:
                return data
            text = data.decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except Exception:
                return text
        except Exception:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return None

    def list_containers(self) -> List[Dict[str, Any]]:
        res = self._request("GET", "/containers/json?all=true")
        return res if isinstance(res, list) else []

    def inspect_container(self, cid: str) -> Optional[Dict[str, Any]]:
        res = self._request("GET", f"/containers/{cid}/json")
        return res if isinstance(res, dict) else None

    def restart_container(self, cid: str) -> bool:
        res = self._request("POST", f"/containers/{cid}/restart")
        return res is not None

    def get_logs(self, cid: str, tail: int = 100) -> str:
        """Fetch, demultiplex, and line-slice Docker container stdout/stderr with timestamps."""
        raw_data = self._request("GET", f"/containers/{cid}/logs?stdout=true&stderr=true&timestamps=true&tail={tail}", raw=True)
        if not raw_data:
            return ""

        lines = []
        is_multiplexed = (
            len(raw_data) > 8
            and raw_data[0] in (0, 1, 2)
            and raw_data[1] == 0
            and raw_data[2] == 0
            and raw_data[3] == 0
        )
        if is_multiplexed:
            offset = 0
            while offset + 8 <= len(raw_data):
                frame_size = int.from_bytes(raw_data[offset + 4 : offset + 8], "big")
                offset += 8
                if frame_size == 0 or offset + frame_size > len(raw_data):
                    break
                payload = raw_data[offset : offset + frame_size]
                offset += frame_size
                text = payload.decode("utf-8", errors="replace")
                for line in text.splitlines():
                    if line.strip():
                        lines.append(line.rstrip())
        else:
            text = raw_data.decode("utf-8", errors="replace")
            for line in text.splitlines():
                if line.strip():
                    lines.append(line.rstrip())

        selected = "\n".join(lines[-tail:])
        # Hard cap at 25 KB per container log payload to prevent network and DB bloat
        max_bytes = 25 * 1024
        if len(selected) > max_bytes:
            selected = selected[-max_bytes:]
        return selected


class SystemMetricsCollector:
    """Gathers accurate server-level CPU, RAM, disk, network, and IP metrics."""

    def __init__(self):
        self._cached_ip = None
        self._last_ip_check = 0
        self._prev_rx_bytes = 0
        self._prev_tx_bytes = 0
        self._prev_net_time = 0.0
        self._prev_cpu_idle = 0.0
        self._prev_cpu_total = 0.0

    def get_public_ip(self) -> str:
        now = time.time()
        if self._cached_ip and (now - self._last_ip_check < 3600):
            return self._cached_ip

        # 1. Try public IP lookups
        for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    ip = resp.read().decode("utf-8").strip()
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                        self._cached_ip = ip
                        self._last_ip_check = now
                        return ip
            except Exception:
                continue

        # 2. Fallback to default route IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("1.1.1.1", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                self._cached_ip = ip
                self._last_ip_check = now
                return ip
        except Exception:
            pass

        return ""

    def get_cpu_percent(self) -> float:
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
            fields = [float(x) for x in line.split()[1:8]]
            idle = fields[3]
            total = sum(fields)

            if self._prev_cpu_total > 0:
                diff_idle = idle - self._prev_cpu_idle
                diff_total = total - self._prev_cpu_total
                self._prev_cpu_idle = idle
                self._prev_cpu_total = total
                return round((1.0 - (diff_idle / diff_total)) * 100.0, 1) if diff_total > 0 else 0.0
            else:
                self._prev_cpu_idle = idle
                self._prev_cpu_total = total
                time.sleep(0.05)
                with open("/proc/stat", "r") as f:
                    line2 = f.readline()
                fields2 = [float(x) for x in line2.split()[1:8]]
                diff_idle = fields2[3] - idle
                diff_total = sum(fields2) - total
                return round((1.0 - (diff_idle / diff_total)) * 100.0, 1) if diff_total > 0 else 0.0
        except Exception:
            try:
                avg = os.getloadavg()
                cores = os.cpu_count() or 1
                return round(min(100.0, (avg[0] / cores) * 100.0), 1)
            except Exception:
                return 0.0

    def get_memory(self) -> Tuple[int, int, float]:
        """Returns (total_mb, used_mb, used_percent)."""
        try:
            mem = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        mem[k.strip()] = int(v.strip().split()[0])
            total = mem.get("MemTotal", 0) // 1024
            avail = mem.get("MemAvailable", mem.get("MemFree", 0)) // 1024
            used = max(0, total - avail)
            pct = round((used / total) * 100.0, 1) if total > 0 else 0.0
            return total, used, pct
        except Exception:
            return 0, 0, 0.0

    def get_disk_root(self) -> Dict[str, Any]:
        try:
            import shutil
            du = shutil.disk_usage("/")
            total_gb = round(du.total / 1e9, 1)
            used_gb = round(du.used / 1e9, 1)
            free_gb = round(du.free / 1e9, 1)
            pct = round((du.used / du.total) * 100.0, 1) if du.total > 0 else 0.0
            return {
                "disk_total_gb": total_gb,
                "disk_used_gb": used_gb,
                "disk_free_gb": free_gb,
                "disk_percent": pct,
            }
        except Exception:
            return {
                "disk_total_gb": 0.0,
                "disk_used_gb": 0.0,
                "disk_free_gb": 0.0,
                "disk_percent": 0.0,
            }

    def get_load_avg(self) -> str:
        s, _ = self.get_load_avg_data()
        return s

    def get_load_avg_data(self) -> Tuple[str, Dict[str, float]]:
        try:
            with open("/proc/loadavg", "r") as f:
                parts = [float(x) for x in f.read().split()[:3]]
                return f"{parts[0]:.2f} {parts[1]:.2f} {parts[2]:.2f}", {
                    "1min": round(parts[0], 2),
                    "5min": round(parts[1], 2),
                    "15min": round(parts[2], 2),
                }
        except Exception:
            try:
                avg = os.getloadavg()
                return f"{avg[0]:.2f} {avg[1]:.2f} {avg[2]:.2f}", {
                    "1min": round(avg[0], 2),
                    "5min": round(avg[1], 2),
                    "15min": round(avg[2], 2),
                }
            except Exception:
                return "0.00 0.00 0.00", {"1min": 0.0, "5min": 0.0, "15min": 0.0}

    def get_network_rates(self) -> Tuple[float, float]:
        """Returns (rx_kbps, tx_kbps)."""
        rx_total = 0
        tx_total = 0
        try:
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()[2:]
                for line in lines:
                    if ":" in line:
                        iface, data = line.split(":", 1)
                        if iface.strip() == "lo":
                            continue
                        cols = data.split()
                        if len(cols) >= 9:
                            rx_total += int(cols[0])
                            tx_total += int(cols[8])
            now = time.time()
            rx_kbps = 0.0
            tx_kbps = 0.0
            if self._prev_net_time > 0:
                dt = now - self._prev_net_time
                if dt > 0:
                    drx = max(0, rx_total - self._prev_rx_bytes)
                    dtx = max(0, tx_total - self._prev_tx_bytes)
                    rx_kbps = round((drx * 8) / (dt * 1000), 1)
                    tx_kbps = round((dtx * 8) / (dt * 1000), 1)
            self._prev_net_time = now
            self._prev_rx_bytes = rx_total
            self._prev_tx_bytes = tx_total
            return rx_kbps, tx_kbps
        except Exception:
            return 0.0, 0.0


class CodebaseDetector:
    """Discovers git repos, branches, and domains from bind mounts & configs."""

    @staticmethod
    def resolve_git_info(mounts: List[Dict[str, Any]], labels: Dict[str, Any] = None) -> Tuple[str, str, str]:
        """Returns (git_repo, git_branch, repo_path)."""
        candidate_paths = []

        # 1. Inspect Docker Compose Labels
        if labels and isinstance(labels, dict):
            compose_dir = labels.get("com.docker.compose.project.working_dir")
            if compose_dir and os.path.exists(compose_dir):
                candidate_paths.append(Path(compose_dir))
            compose_cfg = labels.get("com.docker.compose.project.config_files")
            if compose_cfg and os.path.exists(compose_cfg):
                candidate_paths.append(Path(compose_cfg).parent)

        # 2. Inspect Mounts (both file binds and directory binds)
        for m in mounts:
            if m.get("Type") == "bind":
                src = m.get("Source", "")
                if src:
                    p = Path(src)
                    if p.is_dir():
                        candidate_paths.extend([p, p.parent, p.parent.parent])
                    elif p.is_file():
                        candidate_paths.extend([p.parent, p.parent.parent])

        # 3. Fallback well-known application roots
        for common in ["/opt/Support", "/opt/happy-galileo", "/home/maccs/Support"]:
            if os.path.isdir(common):
                candidate_paths.append(Path(common))

        for p in candidate_paths:
            git_dir = p / ".git"
            if git_dir.exists():
                repo_url = "N/A"
                branch = "main"

                # Parse .git/config
                cfg_file = git_dir / "config" if git_dir.is_dir() else None
                if cfg_file and cfg_file.exists():
                    try:
                        text = cfg_file.read_text(encoding="utf-8", errors="ignore")
                        match = re.search(r'url\s*=\s*(.+)', text)
                        if match:
                            raw_url = match.group(1).strip()
                            if raw_url.endswith(".git"):
                                raw_url = raw_url[:-4]
                            if "github.com:" in raw_url:
                                repo_url = raw_url.split("github.com:", 1)[1]
                            elif "github.com/" in raw_url:
                                repo_url = raw_url.split("github.com/", 1)[1]
                            else:
                                repo_url = raw_url
                    except Exception:
                        pass

                # Parse .git/HEAD
                head_file = git_dir / "HEAD" if git_dir.is_dir() else None
                if head_file and head_file.exists():
                    try:
                        head_text = head_file.read_text(encoding="utf-8", errors="ignore").strip()
                        if "ref: refs/heads/" in head_text:
                            branch = head_text.split("ref: refs/heads/", 1)[1].strip()
                    except Exception:
                        pass

                return repo_url, branch, str(p)

        return "N/A", "N/A", "N/A"

    @staticmethod
    def extract_reverse_proxy_mappings(mounts: List[Dict[str, Any]], labels: Dict[str, Any] = None) -> Tuple[Dict[str, str], List[str]]:
        """
        Parses mounted or discoverable Caddy, Nginx, or Apache configuration files.
        Returns:
            (upstream_to_domain_map, list_of_public_domains)
            e.g. ({'fileserver-api': 'https://files.suburban.ng', '3000': 'https://files.suburban.ng'}, ['files.suburban.ng'])
        """
        upstream_map: Dict[str, str] = {}
        all_domains: List[str] = []
        target_files: List[str] = []

        # 1. Search container bind mounts
        for m in mounts:
            if m.get("Type") == "bind":
                src = m.get("Source", "")
                if src and os.path.exists(src):
                    if os.path.isfile(src) and any(x in src.lower() for x in ["caddyfile", ".conf", "nginx", "httpd", "apache"]):
                        target_files.append(src)
                    elif os.path.isdir(src):
                        for root, _, files in os.walk(src):
                            for f in files:
                                fl = f.lower()
                                if fl in ["caddyfile", "nginx.conf", "default.conf", "httpd.conf"] or fl.endswith(".conf"):
                                    target_files.append(os.path.join(root, f))

        # 2. Search Compose directory
        if labels and isinstance(labels, dict):
            compose_dir = labels.get("com.docker.compose.project.working_dir")
            if compose_dir and os.path.isdir(compose_dir):
                for f in ["Caddyfile", "caddy/Caddyfile", "nginx.conf", "nginx/nginx.conf"]:
                    cand = os.path.join(compose_dir, f)
                    if os.path.isfile(cand) and cand not in target_files:
                        target_files.append(cand)

        for tf in target_files[:10]:
            try:
                with open(tf, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # --- A. CADDYFILE PARSING ---
                caddy_blocks = re.findall(r"([a-zA-Z0-9\-\.]+\.[a-z]{2,12})(?::\d+)?\s*\{([^}]+)\}", content, re.MULTILINE)
                for domain, block in caddy_blocks:
                    if any(x in domain.lower() for x in [".local", ".internal", "localhost", "caddy", "docker"]):
                        continue
                    if domain not in all_domains:
                        all_domains.append(domain)
                    proxy_matches = re.findall(r"(?:reverse_proxy|to)\s+(?:https?:\/\/)?([a-zA-Z0-9\-_]+)(?::(\d+))?", block)
                    for target, port in proxy_matches:
                        t_lower = target.lower()
                        if t_lower not in ["http", "https", "unix", "localhost", "127.0.0.1"]:
                            upstream_map[t_lower] = f"https://{domain}"
                            if port:
                                upstream_map[f"{t_lower}:{port}"] = f"https://{domain}"
                                upstream_map[port] = f"https://{domain}"

                # --- B. NGINX CONFIG PARSING ---
                nginx_servers = re.findall(r"server\s*\{([^}]+)\}", content, re.MULTILINE | re.DOTALL)
                for s_block in nginx_servers:
                    server_names = re.findall(r"server_name\s+([^;]+);", s_block)
                    proxy_passes = re.findall(r"proxy_pass\s+https?:\/\/([a-zA-Z0-9\-_]+)(?::(\d+))?", s_block)
                    domains_in_server = []
                    for sn in server_names:
                        for part in sn.split():
                            part = part.strip()
                            if "." in part and not any(x in part.lower() for x in [".local", "localhost", "127.", "172."]):
                                domains_in_server.append(part)
                                if part not in all_domains:
                                    all_domains.append(part)
                    for domain in domains_in_server:
                        for target, port in proxy_passes:
                            t_lower = target.lower()
                            if t_lower not in ["http", "https", "unix", "localhost", "127.0.0.1"]:
                                upstream_map[t_lower] = f"https://{domain}"
                                if port:
                                    upstream_map[f"{t_lower}:{port}"] = f"https://{domain}"
                                    upstream_map[port] = f"https://{domain}"

                # --- C. APACHE CONFIG PARSING ---
                apache_vhosts = re.findall(r"<VirtualHost[^>]*>(.*?)</VirtualHost>", content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
                for v_block in apache_vhosts:
                    s_name = re.search(r"ServerName\s+([a-zA-Z0-9\-\.]+\.[a-z]{2,12})", v_block, re.IGNORECASE)
                    proxy_passes = re.findall(r"ProxyPass(?:Reverse)?\s+\S+\s+https?:\/\/([a-zA-Z0-9\-_]+)(?::(\d+))?", v_block, re.IGNORECASE)
                    if s_name:
                        domain = s_name.group(1).strip()
                        if domain not in all_domains:
                            all_domains.append(domain)
                        for target, port in proxy_passes:
                            t_lower = target.lower()
                            if t_lower not in ["http", "https", "unix", "localhost", "127.0.0.1"]:
                                upstream_map[t_lower] = f"https://{domain}"
                                if port:
                                    upstream_map[f"{t_lower}:{port}"] = f"https://{domain}"
                                    upstream_map[port] = f"https://{domain}"

            except Exception:
                continue

        return upstream_map, all_domains

    @staticmethod
    def resolve_ingress_url(
        c_name: str,
        env_vars: List[str],
        mounts: List[Dict[str, Any]],
        server_ip: str,
        labels: Dict[str, Any] = None,
        global_upstream_map: Dict[str, str] = None,
        all_discovered_domains: List[str] = None,
        main_port: int = 0
    ) -> str:
        """Auto-detects ingress URL from environment variables, mounted Caddyfiles, Nginx, or Apache."""
        c_lower = c_name.lower()
        is_proxy = any(x in c_lower for x in ["caddy", "nginx", "apache", "httpd", "traefik", "reverse-proxy"])

        # 1. Inspect Environment Variables
        checked_keys = [
            "APP_URL", "SITE_URL", "PUBLIC_URL", "BASE_URL", "WEB_BASE_URL",
            "DOMAIN", "VIRTUAL_HOST", "PUBLIC_HOST", "SERVER_URL", "API_URL",
            "FRONTEND_URL", "LIVEKIT_PUBLIC_URL", "HOST_URL", "APPLICATION_URL",
            "EXTERNAL_URL", "CADDY_DOMAIN"
        ]
        for env in env_vars:
            if "=" in env:
                k, v = env.split("=", 1)
                k_up = k.upper().strip()
                v_val = v.strip()
                if any(x in k_up for x in checked_keys):
                    if "://" in v_val:
                        if not any(x in v_val for x in ["127.0.0.1", "localhost", "172."]):
                            return v_val
                    elif "." in v_val and not v_val.startswith("172.") and not v_val.startswith("127."):
                        return f"https://{v_val}"

        # 2. Check global / node-wide proxy upstream mapping
        if global_upstream_map:
            if c_lower in global_upstream_map:
                return global_upstream_map[c_lower]
            for up_key, up_domain in global_upstream_map.items():
                if up_key in c_lower or c_lower in up_key:
                    return up_domain
            if main_port and str(main_port) in global_upstream_map:
                if any(x in c_lower for x in ["api", "web", "ui", "feed", "worker", "app", "srv", "service"]):
                    return global_upstream_map[str(main_port)]

        # 3. If container IS the reverse proxy itself
        if is_proxy:
            local_map, local_domains = CodebaseDetector.extract_reverse_proxy_mappings(mounts, labels)
            domains = local_domains or all_discovered_domains or []
            if domains:
                return f"https://{domains[0]} (Ingress Proxy)"
            return "[Reverse Proxy Ingress]"

        # 4. Check container's own bind mounts for Caddy/Nginx/Apache files
        local_map, local_domains = CodebaseDetector.extract_reverse_proxy_mappings(mounts, labels)
        if local_map:
            if c_lower in local_map:
                return local_map[c_lower]
            for up_key, up_domain in local_map.items():
                if up_key in c_lower or c_lower in up_key:
                    return up_domain

        return "[INTERNAL]"


class AraAgent:
    """Core Telemetry & Log Streaming Daemon."""

    def __init__(self, hub_url: str, fleet_key: str, node_name: str, base_domain: str = "suburbancloud.ng", insecure: bool = False):
        self.hub_url = hub_url.rstrip("/")
        if not self.hub_url.endswith("/api/telemetry/ingest"):
            self.ingest_url = f"{self.hub_url}/api/telemetry/ingest"
        else:
            self.ingest_url = self.hub_url

        self.fleet_key = fleet_key
        self.node_name = node_name
        self.base_domain = base_domain
        self.insecure = insecure
        self.docker = DockerSocket()
        self.metrics = SystemMetricsCollector()
        self._command_results: List[Dict[str, Any]] = []

    def classify_service(self, name: str, img: str, port: int) -> str:
        combined = f"{name.lower()} {img.lower()}"
        if any(x in combined for x in ["postgres", "mysql", "mariadb", "mongo", "db"]):
            return "database"
        if any(x in combined for x in ["redis", "memcached"]):
            return "cache"
        if any(x in combined for x in ["caddy", "nginx", "traefik", "apache", "httpd", "proxy", "ingress", "gateway"]):
            return "infra"
        if any(x in combined for x in ["api", "orchestrator", "backend", "srv", "livekit"]):
            return "api"
        if any(x in combined for x in ["ui", "frontend", "web", "app", "client", "feed"]):
            return "web"
        if port in (80, 443, 3000, 5000, 8000, 8080):
            return "web"
        return "service"

    def collect_payload(self) -> Dict[str, Any]:
        server_ip = self.metrics.get_public_ip()
        cpu_pct = self.metrics.get_cpu_percent()
        mem_tot_mb, mem_used_mb, mem_pct = self.metrics.get_memory()
        mem_tot_bytes = mem_tot_mb * 1024 * 1024
        mem_used_bytes = mem_used_mb * 1024 * 1024
        disk_info = self.metrics.get_disk_root()
        load_avg_str, load_avg_dict = self.metrics.get_load_avg_data()
        rx_rate, tx_rate = self.metrics.get_network_rates()
        cpu_cores = os.cpu_count() or 1

        containers = self.docker.list_containers()
        services = []

        # Pre-pass: Scan all container mounts & compose labels to build host-wide reverse proxy mapping
        global_upstream_map: Dict[str, str] = {}
        all_discovered_domains: List[str] = []
        container_inspections: Dict[str, Dict[str, Any]] = {}

        for c in containers:
            cid = c.get("Id", "")[:12]
            insp = self.docker.inspect_container(cid) or {}
            container_inspections[cid] = insp
            c_mounts = insp.get("Mounts", [])
            c_labels = insp.get("Config", {}).get("Labels", {})
            up_map, doms = CodebaseDetector.extract_reverse_proxy_mappings(c_mounts, c_labels)
            global_upstream_map.update(up_map)
            for d in doms:
                if d not in all_discovered_domains:
                    all_discovered_domains.append(d)

        for c in containers:
            cid = c.get("Id", "")[:12]
            names = [n.lstrip("/") for n in c.get("Names", [])]
            c_name = names[0] if names else cid
            img = c.get("Image", "")

            # Deep inspect for mounts, ports, env, labels
            inspect_data = container_inspections.get(cid) or {}
            config = inspect_data.get("Config", {})
            env_vars = config.get("Env", [])
            labels = config.get("Labels", {})
            mounts = inspect_data.get("Mounts", [])
            state = inspect_data.get("State", {})

            # Port detection
            ports = []
            for p_spec in c.get("Ports", []):
                pub = p_spec.get("PublicPort")
                priv = p_spec.get("PrivatePort")
                if pub:
                    ports.append(pub)
                elif priv:
                    ports.append(priv)
            main_port = ports[0] if ports else 0

            service_type = self.classify_service(c_name, img, main_port)
            git_repo, git_branch, repo_path = CodebaseDetector.resolve_git_info(mounts, labels)
            access_url = CodebaseDetector.resolve_ingress_url(
                c_name, env_vars, mounts, server_ip, labels,
                global_upstream_map=global_upstream_map,
                all_discovered_domains=all_discovered_domains,
                main_port=main_port
            )

            # REAL LIVE LOGS (100 lines)
            logs = self.docker.get_logs(cid, tail=100)

            created_raw = inspect_data.get("Created") or c.get("Created", "")
            if isinstance(created_raw, (int, float)) and created_raw > 0:
                try:
                    created_at_iso = datetime.datetime.fromtimestamp(created_raw, tz=datetime.timezone.utc).isoformat()
                except Exception:
                    created_at_iso = str(created_raw)
            else:
                created_at_iso = str(created_raw) if created_raw else ""

            # Value-based secret scrubber for environment variables
            sanitized_env = []
            for e in env_vars[:30]:
                if "=" in e:
                    k, v = e.split("=", 1)
                    k_up = k.upper()
                    if any(s in k_up for s in ["PASS", "KEY", "SECRET", "TOKEN", "AUTH", "CREDENTIAL", "PRIVATE", "SALT"]):
                        sanitized_env.append(f"{k}=***REDACTED***")
                    elif re.search(r"://[^:]+:[^@]+@", v):
                        masked_v = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", v)
                        sanitized_env.append(f"{k}={masked_v}")
                    elif v.startswith("Bearer "):
                        sanitized_env.append(f"{k}=Bearer ***REDACTED***")
                    else:
                        sanitized_env.append(e)
                else:
                    sanitized_env.append(e)

            oom_killed = state.get("OOMKilled", False)

            services.append({
                "service_name": c_name,
                "container_name": c_name,
                "container_id": cid,
                "full_id": c.get("Id", ""),
                "image": img,
                "created_at": created_at_iso,
                "started_at": state.get("StartedAt", ""),
                "status": "up" if state.get("Running", False) else state.get("Status", "stopped"),
                "status_detail": c.get("Status", ""),
                "port": main_port,
                "ports": ports,
                "service_type": service_type,
                "repo_path": repo_path if repo_path != "N/A" else "",
                "git_repo": git_repo if git_repo != "N/A" else "",
                "git_branch": git_branch if git_branch != "N/A" else "",
                "access_url": access_url,
                "env": sanitized_env,
                "networks": inspect_data.get("NetworkSettings", {}).get("Networks", {}),
                "restart_policy": inspect_data.get("HostConfig", {}).get("RestartPolicy", {}).get("Name", ""),
                "restart_count": inspect_data.get("RestartCount", 0),
                "exit_code": state.get("ExitCode"),
                "oom_killed": oom_killed,
                "mounts": [{"source": m.get("Source", ""), "destination": m.get("Destination", ""), "type": m.get("Type", "")} for m in mounts if isinstance(m, dict)],
                "logs": logs,
            })

        metrics_obj = {
            "server_ip": server_ip,
            "cpu_percent": cpu_pct,
            "cpu_cores": cpu_cores,
            "cpu_count": cpu_cores,
            "memory_percent": mem_pct,
            "memory_total_mb": mem_tot_mb,
            "memory_used_mb": mem_used_mb,
            "memory": {
                "total_bytes": mem_tot_bytes,
                "used_bytes": mem_used_bytes,
                "total_mb": mem_tot_mb,
                "used_mb": mem_used_mb,
                "usage_percent": mem_pct,
            },
            "load_avg": load_avg_str,
            "load_average": load_avg_dict,
            "disk_total_gb": disk_info["disk_total_gb"],
            "disk_used_gb": disk_info["disk_used_gb"],
            "disk_free_gb": disk_info["disk_free_gb"],
            "disk_percent": disk_info["disk_percent"],
            "net_rx_kbps": rx_rate,
            "net_tx_kbps": tx_rate,
            "network": {
                "rx_kbps": rx_rate,
                "tx_kbps": tx_rate,
                "rx_rate_human": f"{rx_rate} kbps",
                "tx_rate_human": f"{tx_rate} kbps",
            },
            "server": {
                "cpu_cores": cpu_cores,
                "cpu_count": cpu_cores,
                "load_average": load_avg_dict,
                "memory": {
                    "total_bytes": mem_tot_bytes,
                    "used_bytes": mem_used_bytes,
                    "usage_percent": mem_pct,
                },
                "network": {
                    "rx_kbps": rx_rate,
                    "tx_kbps": tx_rate,
                    "rx_rate_human": f"{rx_rate} kbps",
                    "tx_rate_human": f"{tx_rate} kbps",
                }
            }
        }

        payload = {
            "node_name": self.node_name,
            "base_domain": self.base_domain,
            "server_ip": server_ip,
            "status": "ONLINE",
            "enrollment": True,
            "containers_count": len(containers),
            "services_count": len(services),
            "metrics": metrics_obj,
            "services": services,
        }
        return payload

    def send_heartbeat(self) -> bool:
        payload = self.collect_payload()
        if self._command_results:
            payload["command_results"] = list(self._command_results)
            self._command_results.clear()

        raw_json = json.dumps(payload).encode("utf-8")
        compressed_data = gzip.compress(raw_json)

        req = urllib.request.Request(
            self.ingest_url,
            data=compressed_data,
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
                "X-Fleet-Key": self.fleet_key,
                "X-Node-Name": self.node_name,
                "User-Agent": f"ara-agent/{self.node_name}",
            },
            method="POST",
        )

        try:
            import ssl
            ctx = ssl.create_default_context()
            if self.insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200:
                    try:
                        data = json.loads(body)
                        pending_commands = data.get("pending_commands", [])
                        if pending_commands:
                            self.handle_pending_commands(pending_commands)
                    except Exception:
                        pass
                return resp.status == 200
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Telemetry transmission error: {e}")
            return False

    def handle_pending_commands(self, commands: List[Dict[str, Any]]):
        import hmac
        import hashlib
        for cmd in commands:
            cmd_id = cmd.get("id")
            action = cmd.get("action")
            target = cmd.get("target")
            sig = cmd.get("signature")

            payload_str = f"{cmd_id}:{self.node_name}:{action}:{target}"
            expected_sig = hmac.new(self.fleet_key.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_sig, sig or ""):
                print(f"[!] Rejecting unsigned or tampered command {cmd_id}")
                continue

            success = False
            msg = ""
            if action == "restart":
                success = self.docker.restart_container(target)
                msg = f"Container {target} restart: {'SUCCESS' if success else 'FAILED'}"
            else:
                msg = f"Unsupported action '{action}'"

            self._command_results.append({
                "id": cmd_id,
                "status": "SUCCESS" if success else "FAILED",
                "result": {"message": msg, "success": success},
            })

    def run_forever(self, interval_seconds: int = 15):
        print("=" * 65)
        print(f"🛰️  ARA Autonomous Agent Started for '{self.node_name}'")
        print(f"• Central Hub:    {self.ingest_url}")
        print(f"• Ingest Cadence: Every {interval_seconds}s (Gzip Compressed)")
        print(f"• TLS Security:   {'INSECURE (Verification disabled)' if self.insecure else 'STRICT (Certificate verified)'}")
        print(f"• Public IP:      {self.metrics.get_public_ip()}")
        print(f"• Docker Socket:  {self.docker.SOCK_PATH} (available: {self.docker.is_available()})")
        print("=" * 65)

        # Initial immediate heartbeat
        self.send_heartbeat()

        while True:
            time.sleep(interval_seconds)
            try:
                self.send_heartbeat()
            except Exception as e:
                print(f"[!] Heartbeat loop exception: {e}")


def main():
    hub_url = os.environ.get("HUB_URL") or os.environ.get("CENTRAL_HUB_URL") or "https://ara.suburbancloud.ng"
    fleet_key = os.environ.get("FLEET_KEY") or ""
    node_name = os.environ.get("NODE_NAME") or socket.gethostname()
    base_domain = os.environ.get("BASE_DOMAIN") or "suburbancloud.ng"
    insecure = "--insecure" in sys.argv or os.environ.get("INSECURE_TLS") == "1"

    # Command line args override
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hub" and i + 1 < len(args):
            hub_url = args[i + 1]
            i += 2
        elif args[i] == "--fleet-key" and i + 1 < len(args):
            fleet_key = args[i + 1]
            i += 2
        elif args[i] == "--node-name" and i + 1 < len(args):
            node_name = args[i + 1]
            i += 2
        elif args[i] == "--domain" and i + 1 < len(args):
            base_domain = args[i + 1]
            i += 2
        elif args[i] == "--insecure":
            insecure = True
            i += 1
        elif args[i] == "--once":
            if not fleet_key:
                print("FATAL: Fleet key required. Provide --fleet-key <KEY> or set FLEET_KEY.", file=sys.stderr)
                sys.exit(1)
            agent = AraAgent(hub_url, fleet_key, node_name, base_domain, insecure=insecure)
            success = agent.send_heartbeat()
            print("Single heartbeat test:", "SUCCESS" if success else "FAILED")
            sys.exit(0 if success else 1)
        else:
            i += 1

    if not fleet_key:
        print("FATAL: Fleet key required. Provide --fleet-key <KEY> or set FLEET_KEY env var.", file=sys.stderr)
        sys.exit(1)

    agent = AraAgent(hub_url, fleet_key, node_name, base_domain, insecure=insecure)
    agent.run_forever(interval_seconds=15)


if __name__ == "__main__":
    main()
