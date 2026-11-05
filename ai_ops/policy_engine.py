"""
Policy Engine & Rollback Ledger for ARA Autonomous Remediation.

Features:
1. Per-Service Remediation Policy:
   - Configurable action allowance (auto vs. approval-required).
   - Action rate limits (e.g., max restarts per hour, cooldown intervals).
   - Critical service protection (e.g. production databases require explicit approval).
2. Rollback Ledger:
   - Every runtime action logs its preceding state and exact compensation/undo instructions.
   - Provides programmatic and 1-click rollback execution.
"""

import os
import json
import time
import secrets
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from devctl.core.config import Config


class PolicyEngine:
    """Evaluates service remediation policies to permit or require human approval."""

    DEFAULT_POLICY = {
        "auto_remediation_enabled": True,
        "max_auto_restarts_per_hour": 3,
        "cooldown_seconds": 60,
        "require_approval_for_stateful": True,
        "allowed_auto_actions": ["restart_container", "resync_network"],
    }

    def __init__(self, policy_file: Optional[Path] = None):
        self.policy_file = policy_file or Config.DEVCTL_STATE_DIR / "remediation_policy.json"
        self._action_history: Dict[str, List[float]] = {}  # service_name -> [timestamps]

    def _load_policies(self) -> Dict[str, Any]:
        if self.policy_file.exists():
            try:
                with open(self.policy_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"services": {}, "global": self.DEFAULT_POLICY}

    def _save_policies(self, data: Dict[str, Any]):
        self.policy_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.policy_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def get_service_policy(self, service_name: str) -> Dict[str, Any]:
        """Fetch effective policy for a service (service-specific overriding global)."""
        data = self._load_policies()
        global_policy = dict(self.DEFAULT_POLICY)
        global_policy.update(data.get("global", {}))
        svc_policy = data.get("services", {}).get(service_name, {})
        effective = dict(global_policy)
        effective.update(svc_policy)
        return effective

    def set_service_policy(self, service_name: str, policy: Dict[str, Any]):
        """Persist policy overrides for a specific service."""
        data = self._load_policies()
        if "services" not in data:
            data["services"] = {}
        data["services"][service_name] = policy
        self._save_policies(data)

    def evaluate_action(
        self,
        service_name: str,
        action: str,
        is_database: bool = False
    ) -> Tuple[bool, str]:
        """
        Evaluate if an action is permitted to execute automatically.
        Returns (is_permitted, reason).
        """
        policy = self.get_service_policy(service_name)

        # 1. Check master enable flag
        if not policy.get("auto_remediation_enabled", True):
            return False, "Auto-remediation is disabled by policy"

        # 2. Stateful / Database Protection: Databases require human approval for all mutations
        if is_database and policy.get("require_approval_for_stateful", True):
            return False, "Stateful service (database/cache) requires explicit human approval"

        # 3. Action whitelist
        allowed_actions = policy.get("allowed_auto_actions", [])
        if action not in allowed_actions:
            return False, f"Action '{action}' is not in allowed auto actions: {allowed_actions}"

        # 4. Cooldown enforcement
        now = time.time()
        history = self._action_history.get(service_name, [])
        # Prune actions older than 1 hour (3600 seconds)
        recent_history = [t for t in history if (now - t) < 3600]
        self._action_history[service_name] = recent_history

        cooldown = policy.get("cooldown_seconds", 60)
        if recent_history and (now - recent_history[-1]) < cooldown:
            remaining = int(cooldown - (now - recent_history[-1]))
            return False, f"Service is in cooldown period ({remaining}s remaining)"

        # 5. Hourly restart quota
        max_restarts = policy.get("max_auto_restarts_per_hour", 3)
        if len(recent_history) >= max_restarts:
            return False, f"Action limit reached ({len(recent_history)}/{max_restarts} per hour). Escalation required."

        return True, "Action permitted by policy"

    def record_executed_action(self, service_name: str):
        """Record that an action was executed to maintain rate limits."""
        now = time.time()
        if service_name not in self._action_history:
            self._action_history[service_name] = []
        self._action_history[service_name].append(now)


class RollbackLedger:
    """Maintains a persistent record of runtime remediations and compensation steps."""

    def __init__(self, ledger_file: Optional[Path] = None):
        self.ledger_file = ledger_file or Config.DEVCTL_STATE_DIR / "rollback_ledger.json"

    def _load_ledger(self) -> List[Dict[str, Any]]:
        if self.ledger_file.exists():
            try:
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_ledger(self, entries: List[Dict[str, Any]]):
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)

    def record_action(
        self,
        service_name: str,
        container_name: str,
        action: str,
        state_before: Dict[str, Any],
        rollback_command: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an executed runtime action with exact compensation/rollback steps."""
        entry = {
            "id": f"rb-{secrets.token_hex(6)}",
            "service_name": service_name,
            "container_name": container_name,
            "action": action,
            "executed_at": time.time(),
            "state_before": state_before,
            "rollback_command": rollback_command,
            "status": "APPLIED",
            "metadata": metadata or {},
        }
        ledger = self._load_ledger()
        ledger.append(entry)
        # Keep recent 200 actions
        self._save_ledger(ledger[-200:])
        return entry

    def get_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific action by ID."""
        ledger = self._load_ledger()
        for entry in ledger:
            if entry.get("id") == action_id:
                return entry
        return None

    def list_recent_actions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List most recent actions in reverse chronological order."""
        ledger = self._load_ledger()
        return sorted(ledger, key=lambda x: x.get("executed_at", 0), reverse=True)[:limit]
