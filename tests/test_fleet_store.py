"""
Unit tests for Persistent FleetStore (SQLite store, TTL transitions, command queue).
"""

import time
import pytest
from devctl.core.fleet_store import FleetStore, NodeStatus


@pytest.fixture
def temp_fleet_store(tmp_path):
    db_path = tmp_path / "fleet_test.db"
    return FleetStore(db_path=db_path)


def test_upsert_and_get_node(temp_fleet_store):
    payload = {
        "node_name": "worker-eu-01",
        "base_domain": "datakrib.com",
        "containers_count": 5,
        "services_count": 3,
        "open_incidents_count": 1,
        "services": [{"service_name": "api", "port": 8000}]
    }
    temp_fleet_store.upsert_node(payload, client_ip="192.168.1.100")

    node = temp_fleet_store.get_node("worker-eu-01")
    assert node is not None
    assert node["node_name"] == "worker-eu-01"
    assert node["client_ip"] == "192.168.1.100"
    assert node["containers_count"] == 5
    assert node["services_count"] == 3
    assert node["open_incidents_count"] == 1
    assert node["status"] == NodeStatus.ONLINE
    assert node["online"] is True
    assert len(node["services"]) == 1

    all_nodes = temp_fleet_store.get_all_nodes()
    assert len(all_nodes) == 1
    assert all_nodes[0]["node_name"] == "worker-eu-01"


def test_node_ttl_states(temp_fleet_store):
    store = temp_fleet_store
    now = time.time()

    # Insert 3 nodes with different last_seen times directly
    with store._lock:
        conn = store._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO fleet_nodes (
                    node_name, client_ip, base_domain, containers_count, services_count,
                    open_incidents_count, last_seen, registered_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("node-online", "1.1.1.1", "datakrib.com", 1, 1, 0, now - 10, now - 100, '{"node_name": "node-online"}')
            )
            conn.execute(
                """
                INSERT INTO fleet_nodes (
                    node_name, client_ip, base_domain, containers_count, services_count,
                    open_incidents_count, last_seen, registered_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("node-stale", "1.1.1.2", "datakrib.com", 1, 1, 0, now - 60, now - 200, '{"node_name": "node-stale"}')
            )
            conn.execute(
                """
                INSERT INTO fleet_nodes (
                    node_name, client_ip, base_domain, containers_count, services_count,
                    open_incidents_count, last_seen, registered_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("node-offline", "1.1.1.3", "datakrib.com", 1, 1, 0, now - 150, now - 500, '{"node_name": "node-offline"}')
            )
            conn.commit()
        finally:
            conn.close()

    node_online = store.get_node("node-online")
    assert node_online["status"] == NodeStatus.ONLINE
    assert node_online["online"] is True

    node_stale = store.get_node("node-stale")
    assert node_stale["status"] == NodeStatus.STALE
    assert node_stale["online"] is True

    node_offline = store.get_node("node-offline")
    assert node_offline["status"] == NodeStatus.OFFLINE
    assert node_offline["online"] is False


def test_command_lifecycle(temp_fleet_store):
    store = temp_fleet_store
    node_name = "satellite-node-01"

    # 1. Queue command
    cmd = store.queue_command(node_name=node_name, action="restart_container", target="api")
    cmd_id = cmd["id"]
    assert cmd_id.startswith("cmd-")
    assert cmd["status"] == "PENDING"

    # 2. Drain pending commands
    pending = store.drain_pending_commands(node_name)
    assert len(pending) == 1
    assert pending[0]["id"] == cmd_id
    assert pending[0]["action"] == "restart_container"
    assert pending[0]["target"] == "api"

    # Subsequent drain should be empty (delivered)
    pending_again = store.drain_pending_commands(node_name)
    assert len(pending_again) == 0

    # 3. Record command results from node
    store.record_command_results(node_name, [{
        "id": cmd_id,
        "success": True,
        "stdout": "Restarted container api successfully"
    }])

    # 4. Check history
    history = store.get_command_history()
    assert len(history) == 1
    assert history[0]["id"] == cmd_id
    assert history[0]["status"] == "COMPLETED"
    assert history[0]["result"]["success"] is True


def test_prune_offline_nodes(temp_fleet_store):
    store = temp_fleet_store
    now = time.time()

    with store._lock:
        conn = store._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO fleet_nodes (
                    node_name, client_ip, base_domain, containers_count, services_count,
                    open_incidents_count, last_seen, registered_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("active-node", "10.0.0.1", "datakrib.com", 1, 1, 0, now - 10, now, '{}')
            )
            conn.execute(
                """
                INSERT INTO fleet_nodes (
                    node_name, client_ip, base_domain, containers_count, services_count,
                    open_incidents_count, last_seen, registered_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("dead-node", "10.0.0.2", "datakrib.com", 1, 1, 0, now - 4000, now - 5000, '{}')
            )
            conn.commit()
        finally:
            conn.close()

    deleted = store.prune_offline_nodes(max_age_seconds=3600)
    assert deleted == 1

    assert store.get_node("active-node") is not None
    assert store.get_node("dead-node") is None
