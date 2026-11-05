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
