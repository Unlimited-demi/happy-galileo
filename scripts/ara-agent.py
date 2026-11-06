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

class ProxyRule:
    """Represents a discovered routing directive from Caddy, Nginx, Apache, or Traefik."""
    def __init__(self, domain: str, upstream_host: str, upstream_port: int = 0, path: str = "", scheme: str = "https", proxy_type: str = "caddy"):
        self.domain = domain.strip().lower()
        self.upstream_host = upstream_host.strip().lower()
        self.upstream_port = upstream_port
        self.path = path.strip()
        self.scheme = scheme.lower()
        self.proxy_type = proxy_type

    def __repr__(self):
        return f"<ProxyRule {self.scheme}://{self.domain}{self.path} -> {self.upstream_host}:{self.upstream_port} ({self.proxy_type})>"


class NodeReverseProxyEngine:
    """
    Host-wide reverse proxy inspection engine.
    Scans host filesystem (/etc/caddy, /etc/nginx, /etc/apache2, /etc/httpd, etc.),
    container bind-mounts, and compose directories to reconstruct the complete
    ingress routing table for the node without relying on container .env variables.
    """

    @staticmethod
    def _split_blocks_re(text: str, keyword: str) -> List[Tuple[str, str]]:
        """Splits nested configuration blocks (like Nginx server/location) using brace depth."""
        blocks = []
        pattern = re.compile(r'\b' + re.escape(keyword) + r'\b')
        for m in pattern.finditer(text):
            idx = m.start()
            line_start = text.rfind('\n', 0, idx)
            line_prefix = text[line_start+1:idx] if line_start != -1 else text[:idx]
            if '#' in line_prefix:
                continue
            brace_start = text.find('{', idx)
            if brace_start == -1:
                continue
            intermediate = text[idx:brace_start]
            if ';' in intermediate:
                continue
            depth = 1
            pos = brace_start + 1
            while pos < len(text) and depth > 0:
                if text[pos] == '{':
                    depth += 1
                elif text[pos] == '}':
                    depth -= 1
                pos += 1
            body = text[brace_start + 1:pos - 1]
            blocks.append((intermediate.strip(), body))
        return blocks

    @staticmethod
    def parse_caddy(content: str) -> List[ProxyRule]:
        rules = []
        text = content
        # 1. Block-based Caddyfile: domain { ... }
        if '{' in text:
            pos = 0
            while pos < len(text):
                brace_start = text.find('{', pos)
                if brace_start == -1:
                    break
                line_start = text.rfind('\n', 0, brace_start)
                header = text[line_start+1:brace_start].strip() if line_start != -1 else text[:brace_start].strip()
                depth = 1
                curr = brace_start + 1
                while curr < len(text) and depth > 0:
                    if text[curr] == '{':
                        depth += 1
                    elif text[curr] == '}':
                        depth -= 1
                    curr += 1
                body = text[brace_start + 1:curr - 1]
                pos = curr

                if '#' in header or header.startswith('('):
                    continue
                domains = []
                for token in re.split(r'[,\s]+', header):
                    token = re.sub(r'^https?://', '', token.strip()).split(':')[0]
                    if '.' in token and not any(x in token.lower() for x in ['.local', '.internal', 'localhost', '127.', 'caddy', 'docker']):
                        domains.append(token)
                if not domains:
                    continue

                for line in body.splitlines():
                    line_s = line.strip()
                    if not line_s or line_s.startswith('#'):
                        continue
                    if 'reverse_proxy' in line_s or line_s.startswith('to '):
                        path_match = re.search(r'reverse_proxy\s+(/[^\s*]+(?:\*)?)', line_s)
                        path = ''
                        line_targets = line_s
                        if path_match:
                            raw_path = path_match.group(1).rstrip('*').rstrip('/')
                            path = raw_path
                            line_targets = line_s.replace(path_match.group(0), 'reverse_proxy ')

                        targets = re.findall(r'(?:https?:\/\/)?([a-zA-Z0-9\.\-_]+)(?::(\d+))?', line_targets)
                        for tgt, port in targets:
                            t_lower = tgt.lower()
                            if t_lower in ['reverse_proxy', 'to', 'http', 'https', 'header_up', 'lb_policy', 'transport', 'health_path']:
                                continue
                            if t_lower in domains:
                                continue
                            is_ws = 'livekit' in t_lower or 'livekit' in path.lower() or 'ws' in line_s.lower()
                            scheme = 'wss' if is_ws else 'https'
                            for d in domains:
                                rules.append(ProxyRule(d, t_lower, int(port) if port else 0, path, scheme, 'caddy'))
        else:
            # 2. Shorthand single-site Caddyfile without braces
            lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('#')]
            if lines:
                first_line = lines[0]
                first_token = re.sub(r'^https?://', '', first_line).split(':')[0]
                if '.' in first_token and not any(x in first_token.lower() for x in ['.local', 'localhost', '127.']):
                    domain = first_token
                    for line_s in lines[1:]:
                        if 'reverse_proxy' in line_s or line_s.startswith('to '):
                            targets = re.findall(r'(?:https?:\/\/)?([a-zA-Z0-9\.\-_]+)(?::(\d+))?', line_s)
                            for tgt, port in targets:
                                t_lower = tgt.lower()
                                if t_lower not in ['reverse_proxy', 'to', 'http', 'https']:
                                    is_ws = 'livekit' in t_lower or 'ws' in line_s.lower()
                                    scheme = 'wss' if is_ws else 'https'
                                    rules.append(ProxyRule(domain, t_lower, int(port) if port else 0, "", scheme, 'caddy'))
        return rules

    @staticmethod
    def parse_nginx(content: str) -> List[ProxyRule]:
        rules = []
        upstreams = {}
        for header, body in NodeReverseProxyEngine._split_blocks_re(content, 'upstream'):
            u_name = header.split()[-1] if header.split() else ''
            if not u_name:
                continue
            servers = re.findall(r'server\s+([a-zA-Z0-9\.\-_]+)(?::(\d+))?', body)
            upstreams[u_name] = [(s[0], int(s[1]) if s[1] else 0) for s in servers]

        for s_header, s_body in NodeReverseProxyEngine._split_blocks_re(content, 'server'):
            server_names = re.findall(r'server_name\s+([^;]+);', s_body)
            domains = []
            for sn in server_names:
                for part in sn.split():
                    part = part.strip()
                    if '.' in part and not any(x in part.lower() for x in ['.local', 'localhost', '127.', 'caddy', 'docker']):
                        domains.append(part)
            if not domains:
                continue

            loc_blocks = NodeReverseProxyEngine._split_blocks_re(s_body, 'location')
            if not loc_blocks:
                loc_blocks = [('', s_body)]

            for l_header, l_body in loc_blocks:
                l_parts = l_header.split()
                path = l_parts[1].rstrip('*').rstrip('/') if len(l_parts) > 1 and l_parts[1].startswith('/') else ''
                if path in ['/', '/*']:
                    path = ''

                pp_match = re.search(r'proxy_pass\s+https?:\/\/([a-zA-Z0-9\.\-_]+)(?::(\d+))?', l_body)
                if pp_match:
                    tgt = pp_match.group(1)
                    port = int(pp_match.group(2)) if pp_match.group(2) else 0
                    is_ws = 'Upgrade' in l_body or 'upgrade' in l_body or 'livekit' in tgt.lower() or 'livekit' in path.lower()
                    scheme = 'wss' if is_ws else 'https'

                    if tgt in upstreams:
                        for u_host, u_port in upstreams[tgt]:
                            for d in domains:
                                rules.append(ProxyRule(d, u_host, u_port or port, path, scheme, 'nginx'))
                    else:
                        for d in domains:
                            rules.append(ProxyRule(d, tgt, port, path, scheme, 'nginx'))
        return rules

    @staticmethod
    def parse_apache(content: str) -> List[ProxyRule]:
        rules = []
        vhosts = re.findall(r'<VirtualHost[^>]*>(.*?)</VirtualHost>', content, re.DOTALL | re.IGNORECASE)
        for vh in vhosts:
            sn_match = re.search(r'ServerName\s+([a-zA-Z0-9\.\-]+)', vh, re.IGNORECASE)
            if not sn_match:
                continue
            domain = sn_match.group(1).strip()
            if not ('.' in domain and not any(x in domain.lower() for x in ['.local', 'localhost', '127.'])):
                continue
            domains = [domain]
            sa_match = re.search(r'ServerAlias\s+([^\n]+)', vh, re.IGNORECASE)
            if sa_match:
                for part in sa_match.group(1).split():
                    part = part.strip()
                    if '.' in part and not any(x in part.lower() for x in ['.local', 'localhost', '127.']):
                        domains.append(part)

            proxies = re.findall(r'ProxyPass\s+(\S+)\s+(https?|wss?|balancer):\/\/([a-zA-Z0-9\.\-_]+)(?::(\d+))?', vh, re.IGNORECASE)
            for path, proto, tgt, port in proxies:
                scheme = 'wss' if proto.startswith('ws') or 'livekit' in tgt.lower() or 'livekit' in path.lower() else 'https'
                clean_path = '' if path in ['/', '/*'] else path.rstrip('*').rstrip('/')
                for d in domains:
                    rules.append(ProxyRule(d, tgt, int(port) if port else 0, clean_path, scheme, 'apache'))
        return rules

    @classmethod
    def discover_all_configs(cls, container_inspections: List[Dict[str, Any]] = None) -> List[str]:
        """Discovers host reverse proxy configs across system paths, mounts, and compose dirs."""
        files = []

        # 1. Standard host system paths
        system_files = [
            "/etc/caddy/Caddyfile",
            "/etc/caddy/caddy.conf",
            "/etc/nginx/nginx.conf",
            "/etc/apache2/apache2.conf",
            "/etc/apache2/httpd.conf",
            "/etc/httpd/conf/httpd.conf",
            "/usr/local/nginx/conf/nginx.conf",
        ]
        for sf in system_files:
            if os.path.isfile(sf) and sf not in files:
                files.append(sf)

        system_dirs = [
            "/etc/caddy/conf.d",
            "/etc/nginx/conf.d",
            "/etc/nginx/sites-enabled",
            "/etc/nginx/sites-available",
            "/etc/apache2/sites-enabled",
            "/etc/apache2/sites-available",
            "/etc/apache2/conf-enabled",
            "/etc/httpd/conf.d",
            "/etc/httpd/sites-enabled",
        ]
        for sd in system_dirs:
            if os.path.isdir(sd):
                try:
                    for root, _, fs in os.walk(sd):
                        for f in fs:
                            fl = f.lower()
                            if fl.endswith(".conf") or "caddy" in fl:
                                full_p = os.path.join(root, f)
                                if full_p not in files:
                                    files.append(full_p)
                except Exception:
                    pass

        # 2. Container mounts & compose directories
        if container_inspections:
            for insp in container_inspections:
                for m in insp.get("Mounts", []):
                    if isinstance(m, dict) and m.get("Type") == "bind":
                        src = m.get("Source", "")
                        if src and os.path.exists(src):
                            if os.path.isfile(src) and any(x in src.lower() for x in ["caddyfile", ".conf", "nginx", "httpd", "apache"]):
                                if src not in files:
                                    files.append(src)
                            elif os.path.isdir(src):
                                try:
                                    for root, _, fs in os.walk(src):
                                        for f in fs:
                                            fl = f.lower()
                                            if fl in ["caddyfile", "nginx.conf", "default.conf", "httpd.conf"] or fl.endswith(".conf"):
                                                full_p = os.path.join(root, f)
                                                if full_p not in files:
                                                    files.append(full_p)
                                except Exception:
                                    pass

                labels = insp.get("Config", {}).get("Labels", {}) or {}
                compose_dir = labels.get("com.docker.compose.project.working_dir")
                if compose_dir and os.path.isdir(compose_dir):
                    for cand_rel in ["Caddyfile", "caddy/Caddyfile", "nginx.conf", "nginx/nginx.conf", "conf/nginx.conf", "proxy/Caddyfile"]:
                        cand_p = os.path.join(compose_dir, cand_rel)
                        if os.path.isfile(cand_p) and cand_p not in files:
                            files.append(cand_p)

        return files

    @classmethod
    def scan_node(cls, container_inspections: List[Dict[str, Any]] = None) -> List[ProxyRule]:
        """Scans the entire node for reverse proxies and returns all routing rules."""
        config_files = cls.discover_all_configs(container_inspections)
        all_rules: List[ProxyRule] = []

        for cf in config_files[:25]:
            try:
                with open(cf, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                fl = os.path.basename(cf).lower()
                rules = []
                if "caddy" in fl or "reverse_proxy" in content:
                    rules = cls.parse_caddy(content)
                elif "nginx" in fl or "proxy_pass" in content:
                    rules = cls.parse_nginx(content)
                elif "httpd" in fl or "apache" in fl or "proxypass" in content.lower():
                    rules = cls.parse_apache(content)
                all_rules.extend(rules)
            except Exception:
                continue

        return all_rules

    @classmethod
    def get_legacy_mapping(cls, rules: List[ProxyRule]) -> Tuple[Dict[str, str], List[str]]:
        up_map = {}
        all_doms = []
        for r in rules:
            if r.domain not in all_doms:
                all_doms.append(r.domain)
            url = f"{r.scheme}://{r.domain}{r.path.rstrip('*').rstrip('/')}"
            up_map[r.upstream_host] = url
            if r.upstream_port:
                up_map[f"{r.upstream_host}:{r.upstream_port}"] = url
                up_map[str(r.upstream_port)] = url
        return up_map, all_doms

    @classmethod
    def match_container(
        cls,
        c_name: str,
        img: str,
        main_port: int,
        ports: List[int],
        labels: Dict[str, Any],
        inspect_data: Dict[str, Any],
        rules: List[ProxyRule],
        server_ip: str = ""
    ) -> str:
        """Determines container ingress URL strictly from discovered reverse proxy rules. NO .env checking."""
        c_lower = c_name.lstrip("/").lower()
        img_lower = img.lower()

        # 1. Reverse proxy containers themselves are Ingress Gateways, not destination apps
        if any(x in c_lower for x in ["caddy", "nginx", "apache", "httpd", "traefik", "reverse-proxy", "ingress-controller"]) or \
           any(x in img_lower for x in ["caddy", "nginx", "httpd", "apache2", "traefik"]):
            return "[Reverse Proxy Ingress]"

        is_data_service = any(x in c_lower for x in ["postgres", "redis", "mysql", "mariadb", "mongo", "db", "cache"]) or \
                          any(x in img_lower for x in ["postgres", "redis", "mysql", "mariadb", "mongo"])

        aliases = {c_lower}
        svc = (labels.get("com.docker.compose.service") or "").lower()
        if svc:
            aliases.add(svc)
        proj = (labels.get("com.docker.compose.project") or "").lower()

        nets = inspect_data.get("NetworkSettings", {}).get("Networks", {}) if inspect_data else {}
        if isinstance(nets, dict):
            for net_val in nets.values():
                if isinstance(net_val, dict):
                    for al in net_val.get("Aliases", []) or []:
                        if al:
                            aliases.add(al.lower())

        all_ports = set(ports)
        if main_port:
            all_ports.add(main_port)

        loopback_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}
        if server_ip:
            loopback_hosts.add(server_ip)

        # Priority 1: Exact Name / Network Alias / Compose Service Match
        for r in rules:
            if r.upstream_host in aliases:
                path = r.path.rstrip("*").rstrip("/")
                return f"{r.scheme}://{r.domain}{path}"

        # Priority 2: Compose Project + Service Match (e.g. project fileserver + service api = fileserver-api)
        if proj:
            for r in rules:
                if r.upstream_host == f"{proj}-{svc}" or r.upstream_host == f"{proj}_{svc}" or c_lower == f"{proj}-{r.upstream_host}":
                    path = r.path.rstrip("*").rstrip("/")
                    return f"{r.scheme}://{r.domain}{path}"

        # Priority 3: Localhost / Loopback Port Match (proxy forwards to host port)
        for r in rules:
            if r.upstream_host in loopback_hosts and r.upstream_port in all_ports:
                if not is_data_service:
                    path = r.path.rstrip("*").rstrip("/")
                    return f"{r.scheme}://{r.domain}{path}"

        # Priority 4: Distinct Substring Match (ignoring worker/egress suffixes)
        if not c_lower.endswith("-egress") and not c_lower.endswith("_egress") and not is_data_service:
            for r in rules:
                if r.upstream_host not in loopback_hosts and len(r.upstream_host) >= 4:
                    if r.upstream_host in c_lower or c_lower in r.upstream_host:
                        path = r.path.rstrip("*").rstrip("/")
                        return f"{r.scheme}://{r.domain}{path}"

        # Priority 5: Unique Port Match on non-database/cache services
        for r in rules:
            if r.upstream_port in all_ports and not is_data_service:
                if any(x in c_lower for x in ["api", "web", "ui", "feed", "worker", "app", "srv", "service"]):
                    path = r.path.rstrip("*").rstrip("/")
                    return f"{r.scheme}://{r.domain}{path}"

        return "[INTERNAL]"


    @staticmethod
    def extract_reverse_proxy_mappings(mounts: List[Dict[str, Any]], labels: Dict[str, Any] = None) -> Tuple[Dict[str, str], List[str]]:
        """Parses discoverable Caddy, Nginx, or Apache configuration files across node."""
        insp_mock = [{"Mounts": mounts, "Config": {"Labels": labels or {}}}]
        rules = NodeReverseProxyEngine.scan_node(insp_mock)
        return NodeReverseProxyEngine.get_legacy_mapping(rules)

    @staticmethod
    def resolve_ingress_url(
        c_name: str,
        env_vars: List[str] = None,
        mounts: List[Dict[str, Any]] = None,
        server_ip: str = "",
        labels: Dict[str, Any] = None,
        global_upstream_map: Dict[str, str] = None,
        all_discovered_domains: List[str] = None,
        main_port: int = 0,
        rules: List[ProxyRule] = None,
        ports: List[int] = None,
        img: str = "",
        inspect_data: Dict[str, Any] = None,
    ) -> str:
        """Determines ingress URL strictly from reverse proxy rules. NEVER checks container .env."""
        c_lower = c_name.lstrip("/").lower()
        if any(x in c_lower for x in ["caddy", "nginx", "apache", "httpd", "traefik", "reverse-proxy", "ingress-controller"]) or \
           any(x in (img or "").lower() for x in ["caddy", "nginx", "httpd", "apache2", "traefik"]):
            return "[Reverse Proxy Ingress]"

        if rules is not None:
            return NodeReverseProxyEngine.match_container(
                c_name=c_name,
                img=img,
                main_port=main_port,
                ports=ports or ([main_port] if main_port else []),
                labels=labels or {},
                inspect_data=inspect_data or {},
                rules=rules,
                server_ip=server_ip
            )

        if global_upstream_map:
            if c_lower in global_upstream_map:
                return global_upstream_map[c_lower]
            for up_key, up_domain in global_upstream_map.items():
                if up_key in c_lower or c_lower in up_key:
                    return up_domain
            if main_port and str(main_port) in global_upstream_map:
                return global_upstream_map[str(main_port)]

        return "[INTERNAL]"


CodebaseDetector.extract_reverse_proxy_mappings = staticmethod(NodeReverseProxyEngine.extract_reverse_proxy_mappings)
CodebaseDetector.resolve_ingress_url = staticmethod(NodeReverseProxyEngine.resolve_ingress_url)


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

        # 1. Pre-pass: Deep inspect all containers
        container_inspections: Dict[str, Dict[str, Any]] = {}
        for c in containers:
            cid = c.get("Id", "")[:12]
            insp = self.docker.inspect_container(cid) or {}
            container_inspections[cid] = insp

        # 2. Host-wide Reverse Proxy Discovery:
        # Scans system paths (/etc/caddy, /etc/nginx, /etc/apache2, /etc/httpd) + mounts + compose dirs
        rules = NodeReverseProxyEngine.scan_node(list(container_inspections.values()))
        global_upstream_map, all_discovered_domains = NodeReverseProxyEngine.get_legacy_mapping(rules)

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
            access_url = NodeReverseProxyEngine.match_container(
                c_name=c_name,
                img=img,
                main_port=main_port,
                ports=ports,
                labels=labels,
                inspect_data=inspect_data,
                rules=rules,
                server_ip=server_ip
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
