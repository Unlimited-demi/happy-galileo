"""
Unit tests for PolicyEngine and RollbackLedger.
Verifies rate limits, cooldowns, stateful database approval gates, and rollback logging.
"""

import time
import pytest
from ai_ops.policy_engine import PolicyEngine, RollbackLedger


class TestPolicyEngine:
    def test_default_policy_permits_standard_actions(self, tmp_path):
        policy_file = tmp_path / "policy.json"
        engine = PolicyEngine(policy_file=policy_file)

        permitted, reason = engine.evaluate_action("web-frontend", "restart_container", is_database=False)
        assert permitted is True
        assert "permitted" in reason

    def test_database_action_requires_explicit_approval(self, tmp_path):
        policy_file = tmp_path / "policy.json"
        engine = PolicyEngine(policy_file=policy_file)

        # Stateful service must be blocked from automatic remediation
        permitted, reason = engine.evaluate_action("postgres-db", "restart_container", is_database=True)
        assert permitted is False
        assert "Stateful service" in reason
        assert "explicit human approval" in reason

    def test_hourly_restart_rate_limit(self, tmp_path):
        policy_file = tmp_path / "policy.json"
        engine = PolicyEngine(policy_file=policy_file)
        engine.set_service_policy("api-service", {
            "max_auto_restarts_per_hour": 2,
            "cooldown_seconds": 0,  # disable cooldown for rate limit test
            "allowed_auto_actions": ["restart_container"],
        })

        # 1st attempt: OK
        assert engine.evaluate_action("api-service", "restart_container")[0] is True
        engine.record_executed_action("api-service")

        # 2nd attempt: OK
        assert engine.evaluate_action("api-service", "restart_container")[0] is True
        engine.record_executed_action("api-service")

        # 3rd attempt: Rate limit exceeded!
        permitted, reason = engine.evaluate_action("api-service", "restart_container")
        assert permitted is False
        assert "Action limit reached" in reason

    def test_cooldown_period_enforcement(self, tmp_path):
        policy_file = tmp_path / "policy.json"
        engine = PolicyEngine(policy_file=policy_file)
        engine.set_service_policy("worker-service", {
            "max_auto_restarts_per_hour": 5,
            "cooldown_seconds": 120,
            "allowed_auto_actions": ["restart_container"],
        })

        assert engine.evaluate_action("worker-service", "restart_container")[0] is True
        engine.record_executed_action("worker-service")

        # Immediate next attempt blocked by cooldown
        permitted, reason = engine.evaluate_action("worker-service", "restart_container")
        assert permitted is False
        assert "cooldown period" in reason


class TestRollbackLedger:
    def test_record_and_retrieve_rollback_action(self, tmp_path):
        ledger_file = tmp_path / "ledger.json"
        ledger = RollbackLedger(ledger_file=ledger_file)

        entry = ledger.record_action(
            service_name="checkout",
            container_name="checkout-web",
            action="RESTART_CONTAINER",
            state_before={"running": False},
            rollback_command="docker stop checkout-web",
        )

        assert entry["id"].startswith("rb-")
        assert entry["status"] == "APPLIED"

        retrieved = ledger.get_action(entry["id"])
        assert retrieved is not None
        assert retrieved["service_name"] == "checkout"
        assert retrieved["rollback_command"] == "docker stop checkout-web"

    def test_list_recent_actions(self, tmp_path):
        ledger_file = tmp_path / "ledger.json"
        ledger = RollbackLedger(ledger_file=ledger_file)

        ledger.record_action("svc-1", "c-1", "A1", {}, "cmd-1")
        ledger.record_action("svc-2", "c-2", "A2", {}, "cmd-2")

        recent = ledger.list_recent_actions(limit=10)
        assert len(recent) == 2
        assert recent[0]["service_name"] == "svc-2"
