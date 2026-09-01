"""
Fleet State Management for AI-Ops.
Tracks all nodes in the fleet, their heartbeats, services, and metrics.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from devctl.core.config import Config


class FleetState:
    """Manages fleet-wide node state and telemetry."""

    def __init__(self, state_dir: Path = None):
        self.state_dir = state_dir or (Config.DEVCTL_STATE_DIR / "fleet")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.nodes_file = self.state_dir / "nodes.json"
        self._cache = None
        self._cache_time = 0

    def _load_nodes(self) -> Dict[str, Any]:
        """Load nodes from disk with caching."""
        current_time = time.time()
        if self._cache and (current_time - self._cache_time) < 5:
            return self._cache

        try:
            if self.nodes_file.exists():
                data = json.loads(self.nodes_file.read_text(encoding="utf-8"))
                self._cache = data
                self._cache_time = current_time
                return data
        except Exception:
            pass

        return {"nodes": {}}

    def _save_nodes(self, data: Dict[str, Any]):
        """Save nodes to disk."""
        try:
            self.nodes_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._cache = data
            self._cache_time = time.time()
        except Exception as e:
            print(f"[fleet] Error saving state: {e}")

    def update_node(self, node_name: str, telemetry: Dict[str, Any]):
        """Update or create a node with fresh telemetry data."""
        from devctl.commands.fleet import normalize_node_name

        # Normalize node name to prevent duplicates
        normalized_name = normalize_node_name(node_name)

        data = self._load_nodes()
        nodes = data.get("nodes", {})

        # Merge telemetry into existing node data
        if normalized_name not in nodes:
            nodes[normalized_name] = {}

        node = nodes[normalized_name]
        node["last_seen"] = time.time()
        node["node_name"] = normalized_name
        node["base_domain"] = telemetry.get("base_domain", "")
        node["status"] = telemetry.get("status", "ONLINE")
        node["containers_count"] = telemetry.get("containers_count", 0)
        node["services"] = telemetry.get("services", [])
        node["open_incidents"] = telemetry.get("open_incidents", [])
        node["open_incidents_count"] = telemetry.get("open_incidents_count", 0)
        node["metrics"] = telemetry.get("metrics", {})
        node["trends"] = telemetry.get("trends", {})

        data["nodes"] = nodes
        self._save_nodes(data)

    def get_all_nodes(self) -> Dict[str, Any]:
        """Get all nodes in the fleet."""
        data = self._load_nodes()
        return data.get("nodes", {})

    def get_node(self, node_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific node by name."""
        from devctl.commands.fleet import normalize_node_name

        normalized_name = normalize_node_name(node_name)
        nodes = self.get_all_nodes()
        return nodes.get(normalized_name)

    def remove_node(self, node_name: str) -> bool:
        """Remove a node from the fleet."""
        from devctl.commands.fleet import normalize_node_name

        normalized_name = normalize_node_name(node_name)
        data = self._load_nodes()
        nodes = data.get("nodes", {})

        if normalized_name in nodes:
            del nodes[normalized_name]
            data["nodes"] = nodes
            self._save_nodes(data)
            return True

        return False

    def prune_stale_nodes(self, max_age_seconds: int = 3600) -> List[str]:
        """Remove nodes that haven't sent heartbeats within max_age_seconds."""
        current_time = time.time()
        data = self._load_nodes()
        nodes = data.get("nodes", {})

        removed = []
        for node_name in list(nodes.keys()):
            node = nodes[node_name]
            last_seen = node.get("last_seen", 0)
            age_seconds = current_time - last_seen

            if age_seconds > max_age_seconds:
                del nodes[node_name]
                removed.append(node_name)

        if removed:
            data["nodes"] = nodes
            self._save_nodes(data)

        return removed
