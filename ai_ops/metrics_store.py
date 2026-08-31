"""
Time-Series Metrics Store for AI-Ops.
Records per-service health samples (latency, memory, CPU, restarts) into a local
SQLite database and detects gradual degradation trends (memory creep, latency
drift, restart churn) that point-in-time health checks cannot see.

No external dependencies — stdlib sqlite3 only.
"""

import time
import sqlite3
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Any, Optional

from devctl.core.config import Config


class MetricsStore:
    """SQLite-backed rolling time-series store with trend/drift detection."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else (Config.DEVCTL_STATE_DIR / "metrics.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS samples (
                service       TEXT NOT NULL,
                ts            REAL NOT NULL,
                healthy       INTEGER NOT NULL,
                latency_ms    REAL,
                http_status   INTEGER,
                mem_bytes     REAL,
                mem_limit     REAL,
                cpu_pct       REAL,
                restart_count INTEGER
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_svc_ts ON samples(service, ts)")
        self._conn.commit()

    # ── Recording ──

    def record_sample(
        self,
        service: str,
        healthy: bool,
        latency_ms: Optional[float] = None,
        http_status: Optional[int] = None,
        mem_bytes: Optional[float] = None,
        mem_limit: Optional[float] = None,
        cpu_pct: Optional[float] = None,
        restart_count: int = 0,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (service, time.time(), 1 if healthy else 0, latency_ms,
                 http_status, mem_bytes, mem_limit, cpu_pct, restart_count),
            )
            self._conn.commit()

    def prune(self, retention_hours: Optional[int] = None) -> int:
        """Delete samples older than the retention window."""
        hours = retention_hours or Config.METRICS_RETENTION_HOURS
        cutoff = time.time() - hours * 3600
        with self._lock:
            cur = self._conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    # ── Queries ──

    def history(self, service: str, hours: float = 2.0) -> List[Dict[str, Any]]:
        cutoff = time.time() - hours * 3600
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, healthy, latency_ms, http_status, mem_bytes, mem_limit, cpu_pct, restart_count "
                "FROM samples WHERE service = ? AND ts >= ? ORDER BY ts ASC",
                (service, cutoff),
            ).fetchall()
        keys = ["ts", "healthy", "latency_ms", "http_status", "mem_bytes", "mem_limit", "cpu_pct", "restart_count"]
        return [dict(zip(keys, r)) for r in rows]

    def services(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT service FROM samples").fetchall()
        return [r[0] for r in rows]

    # ── Trend / drift detection ──

    @staticmethod
    def _avg(values: List[float]) -> Optional[float]:
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None

    def detect_trends(self, service: str, window_hours: float = 2.0) -> Dict[str, Any]:
        """
        Compare the recent slice of the window against its earlier baseline.

        Warnings raised:
          MEMORY_CREEP   — recent memory > baseline * threshold and grew by >= 50MB
          LATENCY_DRIFT  — recent latency > baseline * threshold and grew by >= 200ms
          RESTART_CHURN  — restart count increased 3+ times within the window
          FLAPPING       — health flipped 4+ times within the window
        """
        samples = self.history(service, hours=window_hours)
        result: Dict[str, Any] = {"service": service, "samples": len(samples), "warnings": []}
        if len(samples) < Config.TREND_MIN_SAMPLES:
            return result

        split = int(len(samples) * 0.7)
        baseline, recent = samples[:split], samples[split:]
        if not baseline or not recent:
            return result

        base_mem = self._avg([s["mem_bytes"] for s in baseline])
        recent_mem = self._avg([s["mem_bytes"] for s in recent])
        if base_mem and recent_mem and base_mem > 0:
            growth = recent_mem - base_mem
            if recent_mem > base_mem * Config.TREND_MEM_GROWTH_FACTOR and growth > 50 * 1024 * 1024:
                result["warnings"].append({
                    "type": "MEMORY_CREEP",
                    "detail": f"Memory grew from {base_mem / 1048576:.0f}MB to {recent_mem / 1048576:.0f}MB "
                              f"over the last {window_hours:g}h — possible leak.",
                })

        base_lat = self._avg([s["latency_ms"] for s in baseline])
        recent_lat = self._avg([s["latency_ms"] for s in recent])
        if base_lat and recent_lat and base_lat > 0:
            if recent_lat > base_lat * Config.TREND_LATENCY_FACTOR and (recent_lat - base_lat) > 200:
                result["warnings"].append({
                    "type": "LATENCY_DRIFT",
                    "detail": f"Response time drifted from {base_lat:.0f}ms to {recent_lat:.0f}ms "
                              f"over the last {window_hours:g}h.",
                })

        restart_vals = [s["restart_count"] for s in samples if s["restart_count"] is not None]
        if restart_vals and (restart_vals[-1] - restart_vals[0]) >= 3:
            result["warnings"].append({
                "type": "RESTART_CHURN",
                "detail": f"Container restarted {restart_vals[-1] - restart_vals[0]} times "
                          f"within the last {window_hours:g}h.",
            })

        flips = sum(1 for a, b in zip(samples, samples[1:]) if a["healthy"] != b["healthy"])
        if flips >= 4:
            result["warnings"].append({
                "type": "FLAPPING",
                "detail": f"Health state flipped {flips} times within the last {window_hours:g}h — unstable service.",
            })

        return result

    def trend_summary(self, window_hours: float = 2.0) -> Dict[str, Any]:
        """Trend verdicts for every service with recorded samples."""
        return {svc: self.detect_trends(svc, window_hours) for svc in self.services()}

    def close(self):
        with self._lock:
            self._conn.close()


def probe_latency(host: str, port: int, timeout: float = 5.0) -> Dict[str, Any]:
    """
    Measure HTTP response time against a service on the internal Docker network.
    Any HTTP response (including 4xx/5xx) yields a latency — only a transport
    failure returns latency None. Timeouts are reported with status -1 so the
    trend engine can distinguish slow services from dead ones. Never raises.
    """
    url = f"http://{host}:{port}/"
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AI-Ops-HealthProbe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return {"latency_ms": (time.monotonic() - start) * 1000, "status": res.status}
    except urllib.error.HTTPError as e:
        return {"latency_ms": (time.monotonic() - start) * 1000, "status": e.code}
    except (TimeoutError, urllib.error.URLError) as e:
        # Distinguish timeout from connection refused — timeout means the service
        # is alive but slow (avoids false LATENCY_DRIFT from 3s cutoff)
        elapsed = (time.monotonic() - start) * 1000
        if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
            return {"latency_ms": elapsed, "status": -1}
        return {"latency_ms": None, "status": None}
    except Exception:
        return {"latency_ms": None, "status": None}
