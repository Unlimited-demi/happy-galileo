"""
Persistent Fleet Store for ARA / ServerGuard Central Hub.
Stores satellite node telemetry, heartbeats, and queued infra commands in SQLite.
Enforces TTL expiration: ONLINE (<=45s), STALE (45-90s), OFFLINE (>90s).
"""

import json
import time
import uuid
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional

from devctl.core.config import Config


class NodeStatus:
    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


class FleetStore:
    """Thread-safe SQLite store for multi-server fleet telemetry and commands."""

    TTL_STALE_SECONDS = 45.0
    TTL_OFFLINE_SECONDS = 90.0

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else (Config.DEVCTL_STATE_DIR / "fleet.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fleet_nodes (
                        node_name             TEXT PRIMARY KEY,
                        client_ip             TEXT,
                        base_domain           TEXT,
                        containers_count      INTEGER DEFAULT 0,
                        services_count        INTEGER DEFAULT 0,
                        open_incidents_count  INTEGER DEFAULT 0,
                        last_seen             REAL NOT NULL,
                        registered_at         REAL NOT NULL,
                        payload_json          TEXT NOT NULL,
                        node_token_hash       TEXT
                    )
                    """
                )
                try:
                    conn.execute("ALTER TABLE fleet_nodes ADD COLUMN node_token_hash TEXT")
                except sqlite3.OperationalError:
                    pass
                conn.execute("CREATE INDEX IF NOT EXISTS idx_fleet_nodes_last_seen ON fleet_nodes(last_seen)")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fleet_commands (
                        id           TEXT PRIMARY KEY,
                        node_name    TEXT NOT NULL,
                        action       TEXT NOT NULL,
                        target       TEXT NOT NULL,
                        created_at   REAL NOT NULL,
                        status       TEXT NOT NULL,
                        executed_at  REAL,
                        result_json  TEXT
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_fleet_cmd_node ON fleet_commands(node_name, status)")
                conn.commit()
            finally:
                conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_node(self, payload: Dict[str, Any], client_ip: str = "127.0.0.1", token_hash: Optional[str] = None) -> Dict[str, Any]:
        """Record or update a node heartbeat payload."""
        node_name = payload.get("node_name", "unknown")
        now = time.time()
        # Prefer payload-specified real server IP if client_ip is internal docker bridge
        if client_ip.startswith("172.") or client_ip.startswith("127.") or client_ip == "localhost":
            real_ip = payload.get("server_ip") or payload.get("node_ip") or payload.get("public_ip")
            if real_ip:
                client_ip = real_ip.strip()

        payload_copy = dict(payload)
        payload_copy["received_at"] = now
        payload_copy["client_ip"] = client_ip

        payload_json = json.dumps(payload_copy)
        base_domain = payload.get("base_domain", Config.BASE_DOMAIN)
        containers_count = int(payload.get("containers_count", 0))
        services_count = int(payload.get("services_count", 0))
        open_incidents_count = int(payload.get("open_incidents_count", 0))

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO fleet_nodes (
                        node_name, client_ip, base_domain, containers_count, services_count,
                        open_incidents_count, last_seen, registered_at, payload_json, node_token_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_name) DO UPDATE SET
                        client_ip = excluded.client_ip,
                        base_domain = excluded.base_domain,
                        containers_count = excluded.containers_count,
                        services_count = excluded.services_count,
                        open_incidents_count = excluded.open_incidents_count,
                        last_seen = excluded.last_seen,
                        payload_json = excluded.payload_json,
                        node_token_hash = COALESCE(excluded.node_token_hash, fleet_nodes.node_token_hash)
                    """,
                    (
                        node_name, client_ip, base_domain, containers_count, services_count,
                        open_incidents_count, now, now, payload_json, token_hash
                    )
                )
                conn.commit()
            finally:
                conn.close()

        return payload_copy

    def validate_node_key(self, node_name: str, key: str) -> bool:
        """
        Verify that the provided telemetry key matches the node's registered token hash,
        or the master FLEET_KEY environment variable. Fails closed.
        """
        if not key or not node_name:
            return False
        import hashlib
        import secrets
        import os

        # Master FLEET_KEY check
        master_key = os.environ.get("FLEET_KEY", "").strip()
        if master_key and secrets.compare_digest(master_key, key):
            return True

        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()

        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("SELECT node_token_hash FROM fleet_nodes WHERE node_name = ?", (node_name,))
                row = cur.fetchone()
                if not row or not row["node_token_hash"]:
                    # Node not registered yet or has no token bound; allow if master key matches
                    return bool(master_key and secrets.compare_digest(master_key, key))
                return secrets.compare_digest(row["node_token_hash"], key_hash)
            finally:
                conn.close()

    def get_node(self, node_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single node by name with current TTL status."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("SELECT * FROM fleet_nodes WHERE node_name = ?", (node_name,))
                row = cur.fetchone()
                if not row:
                    return None
                return self._enrich_node_row(row)
            finally:
                conn.close()

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        """Retrieve all nodes with TTL status calculated."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("SELECT * FROM fleet_nodes ORDER BY last_seen DESC")
                rows = cur.fetchall()
                return [self._enrich_node_row(r) for r in rows]
            finally:
                conn.close()

    def _enrich_node_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Parse payload JSON and calculate live TTL status."""
        try:
            data = json.loads(row["payload_json"])
        except Exception:
            data = {}

        now = time.time()
        last_seen = float(row["last_seen"])
        age = now - last_seen

        if age <= self.TTL_STALE_SECONDS:
            status = NodeStatus.ONLINE
            online = True
        elif age <= self.TTL_OFFLINE_SECONDS:
            status = NodeStatus.STALE
            online = True
        else:
            status = NodeStatus.OFFLINE
            online = False

        data["node_name"] = row["node_name"]
        data["client_ip"] = row["client_ip"]
        data["base_domain"] = row["base_domain"]
        data["status"] = status
        data["online"] = online
        data["last_seen_age_seconds"] = round(age, 1)
        data["last_seen"] = last_seen
        data["registered_at"] = float(row["registered_at"])
        data["containers_count"] = row["containers_count"]
        data["services_count"] = row["services_count"]
        data["open_incidents_count"] = row["open_incidents_count"]
        return data

    def queue_command(self, node_name: str, action: str, target: str) -> Dict[str, Any]:
        """Queue an infra command for a satellite node."""
        cmd_id = f"cmd-{uuid.uuid4().hex[:8]}"
        now = time.time()
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO fleet_commands (id, node_name, action, target, created_at, status)
                    VALUES (?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (cmd_id, node_name, action, target, now)
                )
                conn.commit()
            finally:
                conn.close()

        return {
            "id": cmd_id,
            "node_name": node_name,
            "action": action,
            "target": target,
            "created_at": now,
            "status": "PENDING"
        }

    def drain_pending_commands(self, node_name: str) -> List[Dict[str, Any]]:
        """Fetch and mark pending commands as DELIVERED for node heartbeat response."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute(
                    "SELECT id, node_name, action, target, created_at FROM fleet_commands WHERE node_name = ? AND status = 'PENDING'",
                    (node_name,)
                )
                rows = cur.fetchall()
                if not rows:
                    return []

                cmds = []
                ids = []
                for r in rows:
                    cmds.append({
                        "id": r["id"],
                        "node_name": r["node_name"],
                        "action": r["action"],
                        "target": r["target"],
                        "created_at": r["created_at"],
                    })
                    ids.append(r["id"])

                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE fleet_commands SET status = 'DELIVERED' WHERE id IN ({placeholders})",
                    ids
                )
                conn.commit()
                return cmds
            finally:
                conn.close()

    def record_command_results(self, node_name: str, results: List[Dict[str, Any]]) -> None:
        """Record command execution verdicts reported back from node."""
        now = time.time()
        with self._lock:
            conn = self._get_conn()
            try:
                for res in results:
                    if not isinstance(res, dict):
                        continue
                    cmd_id = res.get("id")
                    if not cmd_id:
                        continue
                    status = "COMPLETED" if res.get("success") else "FAILED"
                    res_json = json.dumps(res)
                    conn.execute(
                        """
                        UPDATE fleet_commands
                        SET status = ?, executed_at = ?, result_json = ?
                        WHERE id = ? AND node_name = ?
                        """,
                        (status, now, res_json, cmd_id, node_name)
                    )
                conn.commit()
            finally:
                conn.close()

    def get_command_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent command logs."""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute(
                    "SELECT * FROM fleet_commands ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                rows = cur.fetchall()
                history = []
                for r in rows:
                    res_data = {}
                    if r["result_json"]:
                        try:
                            res_data = json.loads(r["result_json"])
                        except Exception:
                            pass
                    history.append({
                        "id": r["id"],
                        "node_name": r["node_name"],
                        "action": r["action"],
                        "target": r["target"],
                        "status": r["status"],
                        "created_at": r["created_at"],
                        "executed_at": r["executed_at"],
                        "result": res_data,
                    })
                return history
            finally:
                conn.close()

    def prune_offline_nodes(self, max_age_seconds: float = 3600.0) -> int:
        """Delete nodes that haven't sent a heartbeat for longer than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute("DELETE FROM fleet_nodes WHERE last_seen < ?", (cutoff,))
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()
