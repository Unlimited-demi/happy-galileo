"""
Unit tests for Database & Cache Sealing Enforcement.
Verifies that databases/caches (PostgreSQL, Redis, MySQL, MongoDB, etc.)
are never exposed to 0.0.0.0 or assigned public domains, and require password authentication.
"""

import pytest
from unittest.mock import MagicMock, patch
from devctl.core.docker_mgr import DockerManager
from devctl.core.domains import DomainRegistry, SERVICE_TYPE_DATABASE, SERVICE_TYPE_CACHE
from devctl.cli import cmd_expose
import argparse


class TestDatabaseSecurityAudit:
    @pytest.fixture
    def docker_mgr(self):
        return DockerManager()

    def test_is_database_or_cache_by_name_and_image(self, docker_mgr):
        # Mock container inspect
        with patch.object(docker_mgr, "inspect_container") as mock_inspect:
            mock_inspect.return_value = {
                "Config": {"Image": "postgres:15-alpine"},
            }
            with patch.object(docker_mgr, "detect_ports", return_value=[5432]):
                is_db, desc = docker_mgr.is_database_or_cache("production-db")
                assert is_db is True
                assert "postgres" in desc.lower()

            mock_inspect.return_value = {
                "Config": {"Image": "redis:7.2-alpine"},
            }
            with patch.object(docker_mgr, "detect_ports", return_value=[6379]):
                is_db, desc = docker_mgr.is_database_or_cache("cache-cluster")
                assert is_db is True
                assert "redis" in desc.lower()

            # Normal web app should NOT be database
            mock_inspect.return_value = {
                "Config": {"Image": "node:20-slim"},
            }
            with patch.object(docker_mgr, "detect_ports", return_value=[3000]):
                is_db, desc = docker_mgr.is_database_or_cache("frontend-app")
                assert is_db is False
                assert desc == ""

    def test_audit_database_security_clean(self, docker_mgr):
        """A properly sealed PostgreSQL and Redis with strong passwords should pass."""
        with patch.object(docker_mgr, "inspect_container") as mock_inspect, \
             patch.object(docker_mgr, "detect_ports", return_value=[5432]):
            mock_inspect.return_value = {
                "Config": {
                    "Image": "postgres:16",
                    "Env": ["POSTGRES_PASSWORD=super_secret_strong_pass_123", "POSTGRES_USER=app_user"],
                    "Cmd": ["postgres"],
                },
                "NetworkSettings": {
                    "Ports": {"5432/tcp": None}  # Sealed internally, no host binding
                }
            }
            res = docker_mgr.audit_database_security("app-postgres")
            assert res["is_database"] is True
            assert res["safe"] is True
            assert len(res["violations"]) == 0

        # Redis with requirepass
        with patch.object(docker_mgr, "inspect_container") as mock_inspect, \
             patch.object(docker_mgr, "detect_ports", return_value=[6379]):
            mock_inspect.return_value = {
                "Config": {
                    "Image": "redis:alpine",
                    "Env": [],
                    "Cmd": ["redis-server", "--requirepass", "redis_secret_456"],
                },
                "NetworkSettings": {
                    "Ports": {"6379/tcp": None}
                }
            }
            res = docker_mgr.audit_database_security("app-redis")
            assert res["is_database"] is True
            assert res["safe"] is True
            assert len(res["violations"]) == 0

    def test_audit_database_security_host_exposure_violation(self, docker_mgr):
        """Database with host port published to 0.0.0.0 must trigger CRITICAL violation."""
        with patch.object(docker_mgr, "inspect_container") as mock_inspect, \
             patch.object(docker_mgr, "detect_ports", return_value=[5432]):
            mock_inspect.return_value = {
                "Config": {
                    "Image": "postgres:16",
                    "Env": ["POSTGRES_PASSWORD=pass123"],
                    "Cmd": ["postgres"],
                },
                "NetworkSettings": {
                    "Ports": {
                        "5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5432"}]  # Insecure!
                    }
                }
            }
            res = docker_mgr.audit_database_security("app-postgres")
            assert res["is_database"] is True
            assert res["safe"] is False
            assert any("CRITICAL: Database port 5432/tcp is publicly published to 0.0.0.0:5432" in v for v in res["violations"])

    def test_audit_database_security_unauthenticated_redis(self, docker_mgr):
        """Redis container running without password authentication must trigger CRITICAL violation."""
        with patch.object(docker_mgr, "inspect_container") as mock_inspect, \
             patch.object(docker_mgr, "detect_ports", return_value=[6379]):
            mock_inspect.return_value = {
                "Config": {
                    "Image": "redis:latest",
                    "Env": [],
                    "Cmd": ["redis-server"],  # Missing requirepass
                },
                "NetworkSettings": {
                    "Ports": {"6379/tcp": None}
                }
            }
            res = docker_mgr.audit_database_security("app-redis")
            assert res["is_database"] is True
            assert res["safe"] is False
            assert any("without password authentication" in v for v in res["violations"])

    def test_audit_database_security_postgres_trust_auth(self, docker_mgr):
        """PostgreSQL running with POSTGRES_HOST_AUTH_METHOD=trust must trigger CRITICAL violation."""
        with patch.object(docker_mgr, "inspect_container") as mock_inspect, \
             patch.object(docker_mgr, "detect_ports", return_value=[5432]):
            mock_inspect.return_value = {
                "Config": {
                    "Image": "postgres:15",
                    "Env": ["POSTGRES_HOST_AUTH_METHOD=trust"],
                    "Cmd": ["postgres"],
                },
                "NetworkSettings": {
                    "Ports": {"5432/tcp": None}
                }
            }
            res = docker_mgr.audit_database_security("app-postgres")
            assert res["is_database"] is True
            assert res["safe"] is False
            assert any("POSTGRES_HOST_AUTH_METHOD=trust" in v for v in res["violations"])


class TestDatabaseExposureRejection:
    def test_cmd_expose_rejects_database(self, capsys):
        """'devctl expose' must exit with code 1 and block exposing database services."""
        args = argparse.Namespace(
            service="postgres-db",
            port=5432,
            domain=None,
            env="dev"
        )
        with patch("devctl.cli.DockerManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_cls.return_value = mock_mgr
            mock_mgr.list_containers.return_value = [{"Names": "/postgres-db"}]
            mock_mgr.is_database_or_cache.return_value = (True, "PostgreSQL database (port 5432)")

            with pytest.raises(SystemExit) as exc_info:
                cmd_expose(args)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "EXPOSURE REJECTED" in captured.out
            assert "PostgreSQL database" in captured.out
            assert "NEVER be exposed to public or wildcard domains" in captured.out


class TestDatabaseDiscoverySealing:
    def test_discovery_seals_database_and_prevents_network_injection(self, tmp_path):
        state_file = tmp_path / "state.json"
        with patch("devctl.core.config.Config.STATE_FILE", state_file):
            registry = DomainRegistry()
            with patch("devctl.core.docker_mgr.DockerManager.list_containers") as mock_list, \
                 patch("devctl.core.docker_mgr.DockerManager.inspect_container") as mock_inspect, \
                 patch("devctl.core.docker_mgr.DockerManager.detect_ports") as mock_ports, \
                 patch("devctl.core.docker_mgr.DockerManager.connect_to_network") as mock_connect, \
                 patch("devctl.core.domains.DomainRegistry.detect_existing_domains", return_value={}):

                mock_list.return_value = [
                    {"Names": "/postgres-main", "Image": "postgres:16"},
                    {"Names": "/redis-cache", "Image": "redis:alpine"},
                ]
                
                def inspect_side_effect(name):
                    if "postgres" in name:
                        return {
                            "State": {"Running": True},
                            "Config": {"Image": "postgres:16", "Labels": {}},
                            "NetworkSettings": {"Ports": {"5432/tcp": None}}
                        }
                    elif "redis" in name:
                        return {
                            "State": {"Running": True},
                            "Config": {"Image": "redis:alpine", "Labels": {}},
                            "NetworkSettings": {"Ports": {"6379/tcp": None}}
                        }
                    return None

                mock_inspect.side_effect = inspect_side_effect
                mock_ports.side_effect = lambda name: [5432] if "postgres" in name else [6379]

                discovered = registry.discover_and_index_containers(use_ai=False, force=True)

                # Ensure databases were sealed:
                for d in discovered:
                    if "postgres" in d["container_name"]:
                        assert d["container_type"] == SERVICE_TYPE_DATABASE
                        assert d["url"] is None
                        assert d["domain"] is None
                        assert d["metadata"]["sealed_database"] is True
                        assert d["metadata"]["publicly_exposable"] is False
                    elif "redis" in d["container_name"]:
                        assert d["container_type"] == SERVICE_TYPE_CACHE
                        assert d["url"] is None
                        assert d["domain"] is None
                        assert d["metadata"]["sealed_database"] is True
                        assert d["metadata"]["publicly_exposable"] is False

                # Ensure connect_to_network was NEVER called during discovery
                mock_connect.assert_not_called()

    def test_discovery_skips_excluded_monitoring_containers(self, tmp_path):
        state_file = tmp_path / "state.json"
        with patch("devctl.core.config.Config.STATE_FILE", state_file):
            registry = DomainRegistry()
            with patch("devctl.core.docker_mgr.DockerManager.list_containers") as mock_list, \
                 patch("devctl.core.docker_mgr.DockerManager.inspect_container") as mock_inspect:

                mock_list.return_value = [
                    {"Names": "/foreign-private-app", "Image": "private:latest"},
                ]
                mock_inspect.return_value = {
                    "State": {"Running": True},
                    "Config": {
                        "Image": "private:latest",
                        "Labels": {"ara.monitor": "false"},
                    },
                }

                discovered = registry.discover_and_index_containers(use_ai=False, force=True)
                assert len(discovered) == 0
