import sys
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the project root to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from devctl.core.incident_bus import IncidentBus, IncidentState
from ai_ops.health_checker import HealthChecker
from ai_ops.remediation import RemediationEngine
from ai_ops.telemetry import FleetTelemetryStreamer

class TestIncidentBus:
    def test_create_incident(self, tmp_path):
        bus = IncidentBus(incidents_dir=tmp_path)
        incident = bus.create_incident(
            service_name="test_service",
            title="Test Incident",
            severity="HIGH",
            level=3,
            evidence={"logs": "Error occurred"},
            recommendation="Fix it"
        )
        assert incident["service_name"] == "test_service"
        assert incident["state"] == IncidentState.DETECTED
        
        # Verify JSON + MD files exist
        json_path = tmp_path / f"{incident['id']}.json"
        md_path = tmp_path / f"{incident['id']}.md"
        assert json_path.exists()
        assert md_path.exists()

    def test_list_incidents_open_only(self, tmp_path):
        bus = IncidentBus(incidents_dir=tmp_path)
        # Create 2 open + 1 resolved
        inc1 = bus.create_incident("svc1", "Open 1")
        inc2 = bus.create_incident("svc2", "Open 2")
        inc3 = bus.create_incident("svc3", "Resolved 1")
        bus.resolve_incident(inc3["id"], notes="Fixed")
        
        open_incidents = bus.list_incidents(only_open=True)
        assert len(open_incidents) == 2
        open_ids = {i["id"] for i in open_incidents}
        assert inc1["id"] in open_ids
        assert inc2["id"] in open_ids
        assert inc3["id"] not in open_ids

    def test_claim_incident(self, tmp_path):
        bus = IncidentBus(incidents_dir=tmp_path)
        incident = bus.create_incident("svc1", "Test")
        claimed = bus.claim_incident(incident["id"], agent_name="TestAgent")
        assert claimed["state"] == IncidentState.CLAIMED
        assert claimed["claimed_by"] == "TestAgent"

    def test_resolve_incident(self, tmp_path):
        bus = IncidentBus(incidents_dir=tmp_path)
        incident = bus.create_incident("svc1", "Test")
        resolved = bus.resolve_incident(incident["id"], notes="All fixed", proof={"health_probe": "200 OK"})
        assert resolved["state"] == IncidentState.RESOLVED
        assert resolved["resolution_notes"] == "All fixed"
        assert resolved["resolution_proof"]["health_probe"] == "200 OK"
        assert resolved["resolved_at"] is not None

    def test_dedup_no_duplicate(self, tmp_path):
        bus = IncidentBus(incidents_dir=tmp_path)
        bus.create_incident("svc1", "Test")
        
        # IncidentBus itself does not dedup, dedup logic is in RemediationEngine.
        # This test is just verifying we can identify duplicates manually if needed.
        open_incs = [i for i in bus.list_incidents(only_open=True) if i["service_name"] == "svc1"]
        assert len(open_incs) == 1

    def test_purge_all(self, tmp_path):
        bus = IncidentBus(incidents_dir=tmp_path)
        bus.create_incident("svc1", "Test 1")
        bus.create_incident("svc2", "Test 2")
        bus.create_incident("svc3", "Test 3")
        assert len(bus.list_incidents()) == 3
        count = bus.purge_all_incidents()
        assert count > 0
        assert len(bus.list_incidents()) == 0

class TestHealthChecker:
    @patch('ai_ops.health_checker.DockerSocket')
    def test_healthy_running_container(self, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.inspect_container.return_value = {
            "State": {"Running": True, "OOMKilled": False, "Status": "running"},
            "RestartCount": 0
        }
        mock_docker.get_logs.return_value = "Normal logs"
        
        checker = HealthChecker()
        result = checker.check_container({"service_name": "test", "container_name": "test"})
        assert result["healthy"] is True

    @patch('ai_ops.health_checker.DockerSocket')
    def test_unhealthy_stopped_container(self, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.inspect_container.return_value = {
            "State": {"Running": False, "OOMKilled": False, "Status": "exited"},
            "RestartCount": 0
        }
        mock_docker.get_logs.return_value = "Normal logs"
        
        checker = HealthChecker()
        result = checker.check_container({"service_name": "test", "container_name": "test"})
        assert result["healthy"] is False
        assert any("not running" in r for r in result["failure_reasons"])

    @patch('ai_ops.health_checker.DockerSocket')
    def test_unhealthy_oom_killed(self, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.inspect_container.return_value = {
            "State": {"Running": False, "OOMKilled": True, "Status": "exited"},
            "RestartCount": 0
        }
        mock_docker.get_logs.return_value = ""
        
        checker = HealthChecker()
        result = checker.check_container({"service_name": "test", "container_name": "test"})
        assert result["healthy"] is False
        assert result["oom_killed"] is True

    @patch('ai_ops.health_checker.DockerSocket')
    def test_unhealthy_log_errors(self, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.inspect_container.return_value = {
            "State": {"Running": True, "OOMKilled": False, "Status": "running"},
            "RestartCount": 0
        }
        mock_docker.get_logs.return_value = "Normal logs\nTypeError: Cannot read property 'foo' of undefined\nMore logs"
        
        checker = HealthChecker()
        result = checker.check_container({"service_name": "test", "container_name": "test"})
        assert result["healthy"] is False
        assert result["log_error"] is not None
        assert "TypeError" in result["log_error"]

    @patch('ai_ops.health_checker.DockerSocket')
    def test_unhealthy_docker_healthcheck(self, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.inspect_container.return_value = {
            "State": {"Running": True, "OOMKilled": False, "Status": "running", "Health": {"Status": "unhealthy"}},
            "RestartCount": 0
        }
        mock_docker.get_logs.return_value = ""
        
        checker = HealthChecker()
        result = checker.check_container({"service_name": "test", "container_name": "test"})
        assert result["healthy"] is False
        assert result["docker_health"] == "unhealthy"

    @patch('ai_ops.health_checker.DockerSocket')
    def test_restart_detection(self, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.inspect_container.return_value = {
            "State": {"Running": True, "OOMKilled": False, "Status": "running"},
            "RestartCount": 0
        }
        mock_docker.get_logs.return_value = ""
        
        checker = HealthChecker()
        checker.check_container({"service_name": "test", "container_name": "test"})
        
        mock_docker.inspect_container.return_value["RestartCount"] = 2
        result = checker.check_container({"service_name": "test", "container_name": "test"})
        assert result["new_restarts"] == 2
        assert result["healthy"] is False

class TestRemediation:
    @patch('ai_ops.remediation.DockerSocket')
    def test_level0_healthy(self, mock_docker_cls):
        engine = RemediationEngine()
        result = engine.handle_health_result({
            "service_name": "test",
            "healthy": True
        })
        assert result["action"] == "OBSERVE"

    @patch('ai_ops.remediation.DockerSocket')
    @patch('devctl.core.config.Config.AUTO_REMEDIATION_ENABLED', True)
    @patch('devctl.core.config.Config.MAX_AUTO_RESTARTS', 3)
    def test_level1_auto_restart(self, mock_docker_cls):
        engine = RemediationEngine()
        result = engine.handle_health_result({
            "service_name": "test",
            "healthy": False,
            "container_running": False
        })
        assert result["action"] == "RESTART_CONTAINER"
        mock_docker_cls.return_value.restart_container.assert_called_once()

    @patch('ai_ops.remediation.DockerSocket')
    def test_level3_escalation(self, mock_docker_cls, tmp_path):
        engine = RemediationEngine()
        engine.incident_bus.incidents_dir = tmp_path
        engine.incident_bus.incidents_dir.mkdir(parents=True, exist_ok=True)
        result = engine.handle_health_result({
            "service_name": "test_service",
            "healthy": False,
            "container_running": True,
            "log_error": "TypeError: something wrong"
        })
        assert result["action"] == "ESCALATE_TO_OPENCODE"
        assert "incident_id" in result

    @patch('ai_ops.remediation.DockerSocket')
    def test_dedup_already_reported(self, mock_docker_cls, tmp_path):
        engine = RemediationEngine()
        engine.incident_bus.incidents_dir = tmp_path
        engine.incident_bus.incidents_dir.mkdir(parents=True, exist_ok=True)
        
        engine.handle_health_result({
            "service_name": "test_service",
            "healthy": False,
            "container_running": True,
            "log_error": "TypeError: something wrong"
        })
        
        result2 = engine.handle_health_result({
            "service_name": "test_service",
            "healthy": False,
            "container_running": True,
            "log_error": "TypeError: something wrong"
        })
        assert result2["action"] == "ALREADY_REPORTED"

class TestFleetTelemetry:
    @patch('ai_ops.telemetry.DockerSocket')
    @patch('ai_ops.telemetry.DomainRegistry')
    def test_collect_telemetry_structure(self, mock_registry_cls, mock_docker_cls):
        mock_docker = mock_docker_cls.return_value
        mock_docker.list_containers.return_value = [{"Names": ["/test_container"], "Status": "Up", "Image": "test:v1"}]
        
        mock_registry = mock_registry_cls.return_value
        mock_registry.list_services.return_value = [{"service_name": "test_service", "container_name": "test_container"}]
        
        streamer = FleetTelemetryStreamer()
        payload = streamer.collect_node_telemetry()
        
        assert "node_name" in payload
        assert "base_domain" in payload
        assert "services" in payload
        assert payload["containers_count"] == 1
        assert payload["services_count"] == 1
        assert "open_incidents_count" in payload

    @patch('ai_ops.telemetry.DockerSocket')
    def test_send_heartbeat_no_hub(self, mock_docker_cls):
        streamer = FleetTelemetryStreamer(hub_url="")
        result = streamer.send_heartbeat()
        assert result is False
