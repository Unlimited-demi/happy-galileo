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
        resolved = bus.resolve_incident(incident["id"], notes="All fixed", proof={"health_probe": "200 OK"}, verified=True)
        assert resolved["state"] == IncidentState.VERIFIED
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
        mock_docker_cls.return_value.get_networks.return_value = ["dev-net"]
        engine = RemediationEngine()
        engine.incident_bus.incidents_dir = tmp_path
        engine.incident_bus.incidents_dir.mkdir(parents=True, exist_ok=True)
        result = engine.handle_health_result({
            "service_name": "test_service",
            "healthy": False,
            "container_running": True,
            "log_error": "TypeError: something wrong"
        })
        assert result["action"] in ["ESCALATE_TO_OPENCODE", "ESCALATE_AND_DISPATCH"]
        assert "incident_id" in result

    @patch('ai_ops.remediation.DockerSocket')
    def test_dedup_already_reported(self, mock_docker_cls, tmp_path):
        mock_docker_cls.return_value.get_networks.return_value = ["dev-net"]
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


class TestAIContainerInference:
    def test_database_classification(self):
        from devctl.core.ai_discovery import AIContainerInference, ContainerArchetype
        mock_docker = MagicMock()
        mock_docker.inspect_container.return_value = {
            "Config": {
                "Image": "postgres:15-alpine",
                "Cmd": ["postgres"],
                "Labels": {},
                "Env": ["POSTGRES_DB=app", "POSTGRES_PASSWORD=secret"],
            },
            "NetworkSettings": {"Ports": {"5432/tcp": None}},
        }
        mock_docker.get_logs.return_value = "PostgreSQL database server initialized"

        inference = AIContainerInference(docker=mock_docker)
        profile = inference.inspect_and_infer("my-postgres")

        assert profile["archetype"] == ContainerArchetype.RELATIONAL_DB
        assert profile["is_publicly_exposable"] is False
        assert profile["recommended_port"] == 5432

    def test_redis_cache_classification(self):
        from devctl.core.ai_discovery import AIContainerInference, ContainerArchetype
        mock_docker = MagicMock()
        mock_docker.inspect_container.return_value = {
            "Config": {
                "Image": "redis:7.2-alpine",
                "Cmd": ["redis-server"],
                "Labels": {},
                "Env": [],
            },
            "NetworkSettings": {"Ports": {"6379/tcp": None}},
        }
        mock_docker.get_logs.return_value = "Ready to accept connections"

        inference = AIContainerInference(docker=mock_docker)
        profile = inference.inspect_and_infer("session-redis")

        assert profile["archetype"] == ContainerArchetype.CACHE_STORE
        assert profile["is_publicly_exposable"] is False
        assert profile["recommended_port"] == 6379

    def test_web_frontend_classification(self):
        from devctl.core.ai_discovery import AIContainerInference, ContainerArchetype
        mock_docker = MagicMock()
        mock_docker.inspect_container.return_value = {
            "Config": {
                "Image": "my-nextjs-frontend:latest",
                "Cmd": ["npm", "start"],
                "Labels": {"com.docker.compose.service": "frontend"},
                "Env": ["NEXT_PUBLIC_API_URL=http://api:8000"],
            },
            "NetworkSettings": {"Ports": {"3000/tcp": None}},
        }
        mock_docker.get_logs.return_value = "Next.js ready on http://0.0.0.0:3000"

        inference = AIContainerInference(docker=mock_docker)
        profile = inference.inspect_and_infer("anivault-frontend")

        assert profile["archetype"] == ContainerArchetype.WEB_FRONTEND
        assert profile["is_publicly_exposable"] is True
        assert profile["recommended_port"] == 3000

    def test_codebase_workspace_inspection(self):
        from devctl.core.ai_discovery import AIContainerInference
        mock_docker = MagicMock()
        mock_docker.inspect_container.return_value = {
            "Config": {
                "Image": "anivault-backend:latest",
                "Cmd": ["node", "dist/server.js"],
                "Labels": {
                    "com.docker.compose.project.working_dir": "/opt/anivault",
                    "com.docker.compose.project.config_files": "/opt/anivault/docker-compose.yml",
                    "com.docker.compose.service": "anivault-backend",
                },
                "Env": ["PORT=8070"],
            },
            "Mounts": [
                {"Type": "bind", "Source": "/opt/anivault/backend", "Destination": "/app"}
            ],
            "NetworkSettings": {"Ports": {"8070/tcp": None}},
        }
        mock_docker.get_logs.return_value = "Listening on port 8070"

        inference = AIContainerInference(docker=mock_docker)
        profile = inference.inspect_and_infer("anivault-backend-1")

        assert "codebase" in profile
        cb = profile["codebase"]
        assert cb["workspace_dir"] == "/opt/anivault"
        assert cb["compose_file"] == "/opt/anivault/docker-compose.yml"
        assert cb["compose_service"] == "anivault-backend"
        assert len(cb["bind_mounts"]) == 1
        assert cb["bind_mounts"][0]["host_path"] == "/opt/anivault/backend"

    def test_universal_domain_validation(self):
        from devctl.core.domains import DomainRegistry
        assert DomainRegistry._is_valid_public_domain("mail.example.com") is True
        assert DomainRegistry._is_valid_public_domain("api.my-app.io") is True
        assert DomainRegistry._is_valid_public_domain("dashboard.datakrib.com") is True
        # Invalid / internal
        assert DomainRegistry._is_valid_public_domain("localhost") is False
        assert DomainRegistry._is_valid_public_domain("backend.internal") is False
        assert DomainRegistry._is_valid_public_domain("postgres") is False
        assert DomainRegistry._is_valid_public_domain("127.0.0.1") is False
        assert DomainRegistry._is_valid_public_domain("redis.lan") is False

    def test_docker_socket_fallback_when_cli_missing(self):
        from devctl.core.docker_mgr import DockerManager
        mgr = DockerManager()

        # Mock _run_docker to simulate missing docker binary (FileNotFoundError in container)
        mgr._run_docker = MagicMock(return_value={"success": False, "returncode": -1, "stdout": "", "stderr": "docker executable not found"})

        mock_socket = MagicMock()
        mock_socket.inspect_container.return_value = {
            "State": {"Running": True},
            "Config": {"Image": "my-app:1.0", "ExposedPorts": {"3000/tcp": {}}},
            "NetworkSettings": {"Ports": {"3000/tcp": None}},
        }
        mock_socket.list_containers.return_value = [
            {"Id": "abcdef123456", "Names": ["/my-app"], "Image": "my-app:1.0", "Status": "Up 2 hours", "State": "running"}
        ]
        mock_socket.get_logs.return_value = "Server listening on 3000"
        mock_socket.restart_container.return_value = True

        with patch("ai_ops.docker_socket.DockerSocket", return_value=mock_socket):
            info = mgr.inspect_container("my-app")
            assert info is not None
            assert info["State"]["Running"] is True

            containers = mgr.list_containers()
            assert len(containers) == 1
            assert containers[0]["Names"] == "my-app"

            logs = mgr.get_logs("my-app")
            assert logs == "Server listening on 3000"

            restarted = mgr.restart_container("my-app")
            assert restarted is True

    def test_domain_registry_discovery_docker_socket_fallback(self):
        from devctl.core.domains import DomainRegistry
        reg = DomainRegistry()

        mock_socket = MagicMock()
        mock_socket.list_containers.return_value = [
            {"Id": "111122223333", "Names": ["/devctl-dashboard"], "Image": "python:3.11-slim"},
            {"Id": "444455556666", "Names": ["/caddy"], "Image": "caddy:2-alpine"},
        ]

        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")), \
             patch("ai_ops.docker_socket.DockerSocket", return_value=mock_socket):
            names = reg.get_running_container_names()
            assert "devctl-dashboard" in names
            assert "caddy" in names

    def test_dynamic_caddy_multi_domain_discovery(self, tmp_path):
        from devctl.core.domains import DomainRegistry
        reg = DomainRegistry()

        caddy_file = tmp_path / "Caddyfile"
        caddy_file.write_text("""
status.dev-server.datakrib.com, ara.suburbancloud.ng {
    encode zstd gzip
    reverse_proxy dashboard:8888
}
""", encoding="utf-8")

        with patch("glob.glob", side_effect=lambda pat: [str(caddy_file)] if "Caddyfile" in pat else []):
            domains = reg.detect_existing_domains()
            assert "dashboard:8888" in domains or "dashboard" in domains
            target = domains.get("dashboard") or domains.get("dashboard:8888")
            assert target is not None
            assert target["domain"] == "ara.suburbancloud.ng"

    def test_discover_and_index_resolves_dashboard_without_hardcoding(self, tmp_path):
        from devctl.core.domains import DomainRegistry
        state_file = tmp_path / "state.json"

        with patch("devctl.core.config.Config.STATE_FILE", state_file):
            reg = DomainRegistry()

            # Mock running containers: devctl-dashboard, caddy, ai-ops-daemon
            with patch.object(reg, "get_running_container_names", return_value=["devctl-dashboard", "caddy", "ai-ops-daemon"]), \
                 patch.object(reg, "detect_existing_domains", return_value={
                     "dashboard": {"domain": "ara.suburbancloud.ng", "source": "host-caddy:Caddyfile"},
                     "dashboard:8888": {"domain": "ara.suburbancloud.ng", "source": "host-caddy:Caddyfile"},
                 }), \
                 patch("devctl.core.docker_mgr.DockerManager.inspect_container") as mock_inspect, \
                 patch("devctl.core.docker_mgr.DockerManager.detect_ports") as mock_ports, \
                 patch("devctl.core.docker_mgr.DockerManager.is_database_or_cache", return_value=(False, "")):

                def inspect_mock(name):
                    if name == "devctl-dashboard":
                        return {
                            "State": {"Running": True},
                            "Config": {
                                "Image": "serverguard-dashboard:latest",
                                "Labels": {"com.docker.compose.service": "dashboard"},
                            },
                        }
                    elif name == "caddy":
                        return {
                            "State": {"Running": True},
                            "Config": {"Image": "caddy:2-alpine", "Labels": {}},
                        }
                    elif name == "ai-ops-daemon":
                        return {
                            "State": {"Running": True},
                            "Config": {"Image": "serverguard-ai-ops:latest", "Labels": {}},
                        }
                    return None

                mock_inspect.side_effect = inspect_mock
                mock_ports.side_effect = lambda name: [8888] if name == "devctl-dashboard" else ([80, 443] if name == "caddy" else [])

                discovered = reg.discover_and_index_containers(use_ai=False, force=True)
                assert len(discovered) == 3

                disc_map = {d["container_name"]: d for d in discovered}

                # devctl-dashboard MUST resolve dynamically to ara.suburbancloud.ng
                dashboard = disc_map["devctl-dashboard"]
                assert dashboard["domain"] == "ara.suburbancloud.ng"
                assert dashboard["url"] == "https://ara.suburbancloud.ng"
                assert dashboard["port"] == 8888

                # caddy and ai-ops MUST NOT have public ingress routes
                assert disc_map["caddy"]["url"] is None
                assert disc_map["ai-ops-daemon"]["url"] is None



