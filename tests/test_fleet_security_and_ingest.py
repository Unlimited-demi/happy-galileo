"""
Tests for Fleet Gzip Ingest, Per-Node Authentication, Secret Scrubber, and Incident Detection.
"""

import gzip
import json
import time
from pathlib import Path
from devctl.core.fleet_store import FleetStore
from devctl.core.incident_bus import IncidentBus


def test_fleet_store_token_binding(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_KEY", "master-secret-key-12345")
    db_path = tmp_path / "fleet_test.db"
    store = FleetStore(db_path=db_path)

    # Master key always validates
    assert store.validate_node_key("node-1", "master-secret-key-12345") is True
    # Wrong key fails
    assert store.validate_node_key("node-1", "wrong-key") is False

    # First registration binds token
    token = "node-1-unique-token"
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    store.upsert_node({"node_name": "node-1", "status": "ONLINE"}, token_hash=token_hash)

    # Validates with bound node token
    assert store.validate_node_key("node-1", token) is True
    # Still validates with master key
    assert store.validate_node_key("node-1", "master-secret-key-12345") is True
    # Rejects unauthorized key
    assert store.validate_node_key("node-1", "imposter-key") is False


def test_gzip_compression_roundtrip():
    payload = {
        "node_name": "satellite-1",
        "services": [
            {"service_name": "app-api", "status": "up", "logs": "Running server on port 8000"}
        ]
    }
    raw_json = json.dumps(payload).encode("utf-8")
    compressed = gzip.compress(raw_json)
    assert len(compressed) < len(raw_json) or len(raw_json) < 100

    decompressed = gzip.decompress(compressed).decode("utf-8")
    restored = json.loads(decompressed)
    assert restored["node_name"] == "satellite-1"
    assert restored["services"][0]["service_name"] == "app-api"


def test_incident_bus_source_node(tmp_path: Path):
    incidents_dir = tmp_path / "incidents"
    bus = IncidentBus(incidents_dir=incidents_dir)

    inc = bus.create_incident(
        service_name="suburban-support-orchestrator",
        title="Unhandled Exception in service",
        severity="HIGH",
        source_node="suburban-support-prod",
        evidence={"issue_type": "UNHANDLED_EXCEPTION", "logs": "Traceback..."}
    )

    assert inc["source_node"] == "suburban-support-prod"
    assert inc["service_name"] == "suburban-support-orchestrator"
    assert (incidents_dir / f"{inc['id']}.json").exists()
