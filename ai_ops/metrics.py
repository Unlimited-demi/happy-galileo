"""
Container & Server Metrics Collection for AI-Ops Monitoring.
Collects CPU, memory, disk, and network metrics from Docker containers and the host system.
"""

import subprocess
import time
from typing import Dict, Any, List, Optional
from pathlib import Path


class MetricsCollector:
    """Collects system and container metrics for monitoring and dashboard display."""

    def __init__(self):
        self.last_collection_time = 0
        self.collection_interval = 30  # Collect every 30 seconds
        self.cached_metrics = {}

    def collect_all_metrics(self) -> Dict[str, Any]:
        """Collect both server and container metrics."""
        current_time = time.time()

        # Use cached metrics if collected recently
        if current_time - self.last_collection_time < self.collection_interval:
            return self.cached_metrics

        metrics = {
            "timestamp": int(current_time),
            "server": self.collect_server_metrics(),
            "containers": self.collect_container_metrics(),
        }

        self.cached_metrics = metrics
        self.last_collection_time = current_time
        return metrics

    def collect_server_metrics(self) -> Dict[str, Any]:
        """Collect host server metrics (CPU, memory, disk, load)."""
        metrics = {}

        # CPU Load Average (1min, 5min, 15min)
        try:
            load_avg = Path("/proc/loadavg").read_text().split()
            metrics["load_average"] = {
                "1min": float(load_avg[0]),
                "5min": float(load_avg[1]),
                "15min": float(load_avg[2]),
            }
        except Exception:
            metrics["load_average"] = {"1min": 0, "5min": 0, "15min": 0}

        # Memory Usage
        try:
            mem_info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().split()[0]  # Get numeric value in kB
                    mem_info[key] = int(val) * 1024  # Convert to bytes

            total = mem_info.get("MemTotal", 0)
            available = mem_info.get("MemAvailable", 0)
            used = total - available
            metrics["memory"] = {
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": available,
                "usage_percent": round((used / total * 100) if total > 0 else 0, 1),
            }
        except Exception:
            metrics["memory"] = {"total_bytes": 0, "used_bytes": 0, "usage_percent": 0}

        # Disk Usage (all mounted filesystems)
        try:
            result = subprocess.run(
                ["df", "-B1", "--output=source,size,used,avail,pcent,target"],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
                timeout=5,
            )
            disks = []
            if result.returncode == 0:
                for line in result.stdout.splitlines()[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 6 and parts[0].startswith("/"):
                        disks.append({
                            "device": parts[0],
                            "mount_point": parts[5],
                            "total_bytes": int(parts[1]),
                            "used_bytes": int(parts[2]),
                            "available_bytes": int(parts[3]),
                            "usage_percent": int(parts[4].rstrip("%")),
                        })
            metrics["disks"] = disks
        except Exception:
            metrics["disks"] = []

        # Network Connections (TCP connection count)
        try:
            result = subprocess.run(
                ["ss", "-t", "-H"],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
                timeout=5,
            )
            tcp_connections = len(result.stdout.splitlines()) if result.returncode == 0 else 0
            metrics["network"] = {"tcp_connections": tcp_connections}
        except Exception:
            metrics["network"] = {"tcp_connections": 0}

        # Uptime
        try:
            uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
            metrics["uptime_seconds"] = int(uptime_seconds)
        except Exception:
            metrics["uptime_seconds"] = 0

        return metrics

    def collect_container_metrics(self) -> List[Dict[str, Any]]:
        """Collect metrics for all running Docker containers."""
        containers = []

        try:
            # Use docker stats --no-stream for one-time snapshot
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
                timeout=10,
            )

            if result.returncode != 0:
                return containers

            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[0].strip()
                    cpu_percent = self._parse_percent(parts[1])
                    mem_usage = parts[2].strip()
                    mem_percent = self._parse_percent(parts[3])
                    net_io = parts[4].strip()
                    block_io = parts[5].strip()
                    pids = parts[6].strip()

                    # Parse memory usage (e.g., "100MiB / 1GiB")
                    mem_parts = mem_usage.split("/")
                    mem_used = self._parse_bytes(mem_parts[0].strip()) if len(mem_parts) > 0 else 0
                    mem_limit = self._parse_bytes(mem_parts[1].strip()) if len(mem_parts) > 1 else 0

                    containers.append({
                        "name": name,
                        "cpu_percent": cpu_percent,
                        "memory_used_bytes": mem_used,
                        "memory_limit_bytes": mem_limit,
                        "memory_percent": mem_percent,
                        "network_io": net_io,
                        "block_io": block_io,
                        "pids": int(pids) if pids.isdigit() else 0,
                    })

        except Exception as e:
            print(f"[metrics] Error collecting container metrics: {e}")

        return containers

    def _parse_percent(self, s: str) -> float:
        """Parse percentage string like '12.34%' to float."""
        try:
            return float(s.strip().rstrip("%"))
        except (ValueError, AttributeError):
            return 0.0

    def _parse_bytes(self, s: str) -> int:
        """Parse byte string like '100MiB', '1.5GiB' to bytes."""
        try:
            s = s.strip().upper()
            multipliers = {
                "B": 1,
                "KB": 1024,
                "KIB": 1024,
                "MB": 1024**2,
                "MIB": 1024**2,
                "GB": 1024**3,
                "GIB": 1024**3,
                "TB": 1024**4,
                "TIB": 1024**4,
            }
            for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
                if s.endswith(suffix):
                    num = float(s[:-len(suffix)].strip())
                    return int(num * mult)
            return int(float(s))
        except (ValueError, AttributeError):
            return 0
