"""
Unit tests for ARA BrainEngine (Local CPU model integration).
"""

import pytest
from unittest.mock import MagicMock, patch
from ai_ops.brain import BrainEngine


class TestBrainEngine:
    def test_explain_incident_deterministic_fallbacks(self):
        """When local model is offline/unreachable, BrainEngine must return accurate deterministic explanations."""
        brain = BrainEngine(brain_url="http://invalid-host:9999")

        # 1. OOM failure
        oom_exp = brain.explain_incident("order-service", "oom", "Process exited with code 137 (OOM)")
        assert "OOM-killer" in oom_exp or "memory" in oom_exp

        # 2. 502 Bad Gateway
        gateway_exp = brain.explain_incident("frontend", "ingress_failure", "HTTP 502 Bad Gateway from upstream")
        assert "502 Bad Gateway" in gateway_exp
        assert "frontend" in gateway_exp

        # 3. Connection refused
        conn_exp = brain.explain_incident("cache", "connection_error", "dial tcp 127.0.0.1:6379: connection refused")
        assert "refused internal TCP connections" in conn_exp

    def test_explain_incident_with_mocked_llm(self):
        """When local brain responds, BrainEngine must parse and return the generated explanation."""
        brain = BrainEngine(brain_url="http://localhost:11434")

        with patch.object(brain, "is_available", return_value=True), \
             patch("urllib.request.urlopen") as mock_urlopen:

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b'{"response": "The payment gateway timed out due to database connection exhaustion."}'
            mock_urlopen.return_value.__enter__.return_value = mock_response

            explanation = brain.explain_incident(
                service_name="payment-api",
                error_category="timeout",
                error_logs="TimeoutError: pool exhausted after 30000ms"
            )
            assert "database connection exhaustion" in explanation

    def test_chatops_tool_dispatch(self):
        """BrainEngine ChatOps should correctly inspect fleet, rollback, or incident context."""
        brain = BrainEngine()

        # Query fleet status
        mock_fleet_store = MagicMock()
        mock_fleet_store.get_all_nodes.return_value = [
            {"node_name": "vm-01", "status": "ONLINE", "services_count": 5},
            {"node_name": "vm-02", "status": "ONLINE", "services_count": 3},
        ]
        res = brain.handle_chatops_query("how are the fleet nodes doing?", fleet_store=mock_fleet_store)
        assert "vm-01" in res["answer"] and "ONLINE" in res["answer"]
        assert "vm-02" in res["answer"] and "ONLINE" in res["answer"]

        # Query incidents
        with patch("devctl.core.incident_bus.IncidentBus.list_incidents") as mock_list:
            mock_list.return_value = [
                {"id": "INC-001", "service_name": "checkout", "severity": "HIGH"}
            ]
            res_inc = brain.handle_chatops_query("are there any active incidents?")
            assert "INC-001" in res_inc["answer"]
            assert "checkout" in res_inc["answer"]

        # Query general status
        with patch("devctl.core.incident_bus.IncidentBus.list_incidents") as mock_list:
            mock_list.return_value = [
                {"id": "INC-999", "service_name": "billing-api", "severity": "CRITICAL"}
            ]
            res_status = brain.handle_chatops_query("what are the status")
            assert "Central Hub (vm-test)" in res_status["answer"]
            assert "INC-999" in res_status["answer"]
            assert "billing-api" in res_status["answer"]

        # Query specific service diagnostics (e.g. devctl-dashboard flapping)
        with patch("ai_ops.metrics_store.MetricsStore.detect_trends") as mock_trends, \
             patch("devctl.core.incident_bus.IncidentBus.list_incidents") as mock_list:
            mock_trends.return_value = {
                "service": "devctl-dashboard",
                "samples": 100,
                "verdict": "UNSTABLE",
                "warnings": [{"type": "FLAPPING", "detail": "Health state flipped 12 times"}],
                "mem_growth_pct": 0.0,
                "latency_factor": 1.0,
            }
            mock_list.return_value = [
                {"id": "INC-042", "service_name": "devctl-dashboard", "severity": "HIGH", "title": "Crash loop"}
            ]
            res_flap = brain.handle_chatops_query("what is causing the flapping on devctl-dashboard?")
            assert "devctl-dashboard" in res_flap["answer"]
            assert "FLAPPING" in res_flap["answer"]
            assert "INC-042" in res_flap["answer"]

    def test_react_tool_calling_loop(self):
        """When local model decides to call tools, ARA executes them and feeds observations back to Qwen."""
        import json
        brain = BrainEngine(brain_url="http://localhost:11434")

        # Step 1: LLM returns tool_calls for get_service_telemetry
        mock_step1 = MagicMock()
        mock_step1.status = 200
        mock_step1.__enter__.return_value = mock_step1
        mock_step1.read.return_value = json.dumps({
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_service_telemetry",
                            "arguments": {"service_name": "devctl-dashboard"}
                        }
                    }
                ]
            }
        }).encode("utf-8")

        # Step 2: LLM receives tool observation and writes final answer
        mock_step2 = MagicMock()
        mock_step2.status = 200
        mock_step2.__enter__.return_value = mock_step2
        mock_step2.read.return_value = json.dumps({
            "message": {
                "role": "assistant",
                "content": "The flapping on devctl-dashboard was caused by 12 health state transitions during startup."
            }
        }).encode("utf-8")

        with patch.object(brain, "is_available", return_value=True), \
             patch("urllib.request.urlopen", side_effect=[mock_step1, mock_step2]), \
             patch.object(brain, "_execute_tool", return_value={"warnings": [{"detail": "12 flips"}]}) as mock_exec:

            res = brain.handle_chatops_query("what is causing the flapping on devctl-dashboard?")
            mock_exec.assert_called_once_with("get_service_telemetry", {"service_name": "devctl-dashboard"}, fleet_store=None)
            assert "The flapping on devctl-dashboard" in res["answer"]
            assert res["engine"] == f"ara-brain-react-{brain.model}"
            assert len(res["context_data"]["executed_tools"]) == 1

    def test_new_sre_tools_execution(self, tmp_path):
        """Verify get_container_logs, get_service_routes, get_system_doctor, and remediation tools."""
        brain = BrainEngine()

        # 1. get_container_logs
        with patch("ai_ops.docker_socket.DockerSocket.get_logs", return_value="Error: Connection pool exhausted\nStack trace: ..."):
            logs_res = brain._execute_tool("get_container_logs", {"service_name": "billing-api", "tail": 20})
            assert logs_res["service"] == "billing-api"
            assert "Connection pool exhausted" in logs_res["logs"]

        # 2. get_service_routes
        with patch("devctl.core.domains.DomainRegistry.list_services", return_value=[
            {"service_name": "billing-api", "url": "https://billing-api.suburbancloud.ng", "port": 8000, "env": "dev"}
        ]):
            routes_res = brain._execute_tool("get_service_routes", {})
            assert len(routes_res) == 1
            assert routes_res[0]["service"] == "billing-api"

        # 3. get_system_doctor
        with patch("ai_ops.docker_socket.DockerSocket.list_containers", return_value=[{"Names": ["/caddy"]}]), \
             patch("devctl.core.caddy.CaddyManager.check_health", return_value=True):
            doc_res = brain._execute_tool("get_system_doctor", {})
            assert doc_res["docker_engine"] == "RUNNING"
            assert doc_res["caddy_admin_api"] == "REACHABLE"
            assert doc_res["overall_status"] == "HEALTHY"
            assert "https://ara.suburbancloud.ng" in doc_res["dashboard_url"]

        # 4. request_remediation (Approval Required for Stateful Database)
        with patch("ai_ops.policy_engine.PolicyEngine.evaluate_action", return_value=(False, "Stateful service requires human approval")), \
             patch("devctl.core.config.Config.DEVCTL_STATE_DIR", tmp_path):
            rem_res = brain._execute_tool("request_remediation", {
                "service_name": "postgres-db",
                "action": "restart_container",
                "reason": "OOM recovery"
            })
            assert rem_res["status"] == "APPROVAL_REQUIRED"
            assert "APP-" in rem_res["approval_id"]
            app_id = rem_res["approval_id"]

            # 5. approve_remediation
            with patch("ai_ops.docker_socket.DockerSocket.restart_container", return_value=True):
                appr_res = brain._execute_tool("approve_remediation", {"approval_id": app_id})
                assert appr_res["status"] == "EXECUTED"
                assert "successfully executed" in appr_res["message"]

    def test_get_fleet_nodes_with_real_ips_and_storage(self):
        """BrainEngine must return real IPs and storage metrics from live node payloads."""
        brain = BrainEngine()
        mock_fs = MagicMock()
        mock_fs.get_all_nodes.return_value = [
            {
                "node_name": "suburban-support-prod",
                "status": "ONLINE",
                "server_ip": "102.38.58.99",
                "containers_count": 4,
                "metrics": {
                    "disk_total_gb": 52.5,
                    "disk_free_gb": 31.3,
                    "disk_used_gb": 18.5,
                    "disk_percent": 35.2,
                    "cpu_percent": 0.5,
                    "memory_percent": 45.4
                }
            },
            {
                "node_name": "hub-vm",
                "status": "ONLINE",
                "client_ip": "41.73.0.6",
                "containers_count": 4,
                "metrics": {
                    "server": {
                        "disks": [{"total_bytes": 105490411520, "available_bytes": 73761751040, "used_bytes": 27202551808, "usage_percent": 27}],
                        "memory": {"usage_percent": 39.7},
                        "load_average": {"1min": 0.1}
                    }
                }
            }
        ]

        nodes = brain._execute_tool("get_fleet_nodes", {}, fleet_store=mock_fs)
        assert len(nodes) == 2
        # Verify suburban-support-prod
        support = next(n for n in nodes if n["node_name"] == "suburban-support-prod")
        assert support["server_ip"] == "102.38.58.99"
        assert support["storage_free_gb"] == 31.3
        assert support["storage_total_gb"] == 52.5

        # Verify hub-vm
        hub = next(n for n in nodes if n["node_name"] == "hub-vm")
        assert hub["server_ip"] == "41.73.0.6"
        assert hub["storage_free_gb"] == 68.7
        assert hub["storage_total_gb"] == 98.2

        # Verify natural language query returns real IPs and storage
        res = brain.handle_chatops_query("what is the ip address of the support node?", fleet_store=mock_fs)
        assert "102.38.58.99" in res["answer"] or "102.38.58.99" in res["reply"]

        res_storage = brain.handle_chatops_query("what is the storage available on suburban-support-prod?", fleet_store=mock_fs)
        assert "31.3" in res_storage["answer"] or "31.3" in res_storage["reply"]

