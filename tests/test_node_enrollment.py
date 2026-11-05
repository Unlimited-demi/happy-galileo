"""
Tests for NodeManager and devctl node enroll / status commands.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from devctl.commands.node import NodeManager
from devctl.core.config import Config


@pytest.fixture
def temp_node_config(tmp_path, monkeypatch):
    """Fixture pointing NodeManager CONFIG_FILE to a temporary path."""
    state_dir = tmp_path / ".devctl"
    state_dir.mkdir(parents=True, exist_ok=True)
    cfg_file = state_dir / "fleet_node.json"
    monkeypatch.setattr(NodeManager, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(Config, "DEVCTL_STATE_DIR", state_dir)
    return cfg_file


def test_normalize_hub_url():
    """Verify hub URL normalization handles various user input formats."""
    # Base URL with no trailing slash
    ingest, base = NodeManager.normalize_hub_url("https://hub.example.com")
    assert ingest == "https://hub.example.com/api/telemetry/ingest"
    assert base == "https://hub.example.com"

    # Base URL with trailing slash
    ingest, base = NodeManager.normalize_hub_url("https://hub.example.com/")
    assert ingest == "https://hub.example.com/api/telemetry/ingest"
    assert base == "https://hub.example.com"

    # Already full ingest URL
    ingest, base = NodeManager.normalize_hub_url("https://hub.example.com/api/telemetry/ingest")
    assert ingest == "https://hub.example.com/api/telemetry/ingest"
    assert base == "https://hub.example.com"

    # Missing scheme (defaults to https://)
    ingest, base = NodeManager.normalize_hub_url("hub.example.com:8443")
    assert ingest == "https://hub.example.com:8443/api/telemetry/ingest"
    assert base == "https://hub.example.com:8443"


def test_node_enroll_success(temp_node_config):
    """Test successful node enrollment writes config and returns expected data."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"status": "received", "node": "worker-01"}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response), \
         patch("ai_ops.docker_socket.DockerSocket.list_containers", return_value=[]):
        res = NodeManager.enroll(
            hub_url="https://hub.example.com",
            token="secret-fleet-token",
            node_name="worker-01",
            dry_run=False,
        )

    assert res["success"] is True
    assert res["node_name"] == "worker-01"
    assert res["hub_url"] == "https://hub.example.com/api/telemetry/ingest"
    assert temp_node_config.exists()

    saved_data = json.loads(temp_node_config.read_text(encoding="utf-8"))
    assert saved_data["enrolled"] is True
    assert saved_data["node_name"] == "worker-01"
    assert saved_data["fleet_key"] == "secret-fleet-token"


def test_node_enroll_dry_run(temp_node_config):
    """Test dry run performs handshake but does NOT write config file."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"status": "received"}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response), \
         patch("ai_ops.docker_socket.DockerSocket.list_containers", return_value=[]):
        res = NodeManager.enroll(
            hub_url="https://hub.example.com",
            token="secret-fleet-token",
            node_name="worker-dry",
            dry_run=True,
        )

    assert res["success"] is True
    assert res["dry_run"] is True
    assert not temp_node_config.exists()


def test_node_enroll_auth_failure(temp_node_config):
    """Test enrollment failure when Hub rejects token with 401."""
    import urllib.error
    http_error = urllib.error.HTTPError(
        url="https://hub.example.com/api/telemetry/ingest",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=None,
    )

    with patch("urllib.request.urlopen", side_effect=http_error), \
         patch("ai_ops.docker_socket.DockerSocket.list_containers", return_value=[]):
        res = NodeManager.enroll(
            hub_url="https://hub.example.com",
            token="wrong-token",
            node_name="worker-01",
        )

    assert res["success"] is False
    assert "Invalid fleet token" in res["error"]
    assert not temp_node_config.exists()


def test_node_status_not_enrolled(temp_node_config, monkeypatch):
    """Test status when node is not enrolled."""
    monkeypatch.delenv("CENTRAL_HUB_URL", raising=False)
    monkeypatch.delenv("FLEET_KEY", raising=False)
    status = NodeManager.get_status(ping_hub=False)
    assert status["enrolled"] is False
    assert status["status"] == "NOT_ENROLLED"


def test_node_status_enrolled_and_connected(temp_node_config):
    """Test status when node is enrolled and hub ping succeeds."""
    temp_node_config.write_text(json.dumps({
        "enrolled": True,
        "node_name": "worker-02",
        "hub_url": "https://hub.example.com/api/telemetry/ingest",
        "fleet_key": "valid-token",
        "tls_verify": True,
    }), encoding="utf-8")

    with patch("ai_ops.telemetry.FleetTelemetryStreamer.send_heartbeat", return_value=True):
        status = NodeManager.get_status(ping_hub=True)

    assert status["enrolled"] is True
    assert status["node_name"] == "worker-02"
    assert status["connection"] == "CONNECTED"
