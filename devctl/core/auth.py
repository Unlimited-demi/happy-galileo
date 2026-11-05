"""
Authentication module for ServerGuard.
Manages API keys for dashboard access, telemetry ingestion, and Role-Based Access Control (RBAC).
"""
import os
import json
import secrets
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from .config import Config

# RBAC Role Definitions
ROLE_VIEWER = "viewer"       # Read-only access to services and metrics
ROLE_OPERATOR = "operator"   # Can queue whitelisted infra playbook actions
ROLE_APPROVER = "approver"   # Can approve/reject remediation PRs & plans
ROLE_ADMIN = "admin"         # Full administrative control (dispatch, purge, prune, manage keys)

ROLE_HIERARCHY = {
    ROLE_VIEWER: 1,
    ROLE_OPERATOR: 2,
    ROLE_APPROVER: 3,
    ROLE_ADMIN: 4,
}


class AuthManager:
    """Manages API keys and RBAC for dashboard and telemetry authentication."""

    def __init__(self, auth_file: Optional[Path] = None):
        self.auth_file = auth_file or Config.DEVCTL_STATE_DIR / "auth.json"

    def _load_auth(self) -> Dict[str, Any]:
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_auth(self, data: Dict[str, Any]):
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.auth_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def setup_keys(self) -> Dict[str, str]:
        """Generate API keys on first install. Returns the raw keys (only shown once)."""
        data = self._load_auth()
        if data.get('initialized'):
            return {'dashboard_key': '***', 'telemetry_key': '***', 'already_initialized': True}

        dashboard_key = secrets.token_urlsafe(32)
        telemetry_key = secrets.token_urlsafe(32)

        data['dashboard_key_hash'] = hashlib.sha256(dashboard_key.encode()).hexdigest()
        data['telemetry_key_hash'] = hashlib.sha256(telemetry_key.encode()).hexdigest()
        data['roles'] = {
            data['dashboard_key_hash']: {"role": ROLE_ADMIN, "name": "Default Admin Key"}
        }
        data['initialized'] = True
        self._save_auth(data)

        return {'dashboard_key': dashboard_key, 'telemetry_key': telemetry_key}

    def create_role_key(self, role: str, name: str = "") -> str:
        """Create a new API key with a designated RBAC role."""
        if role not in ROLE_HIERARCHY:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {list(ROLE_HIERARCHY.keys())}")

        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        data = self._load_auth()
        if "roles" not in data:
            data["roles"] = {}
        data["roles"][key_hash] = {
            "role": role,
            "name": name or f"{role.capitalize()} Key",
        }
        self._save_auth(data)
        return raw_key

    def get_role_for_key(self, key: str) -> Optional[str]:
        """
        Determine the RBAC role for a given API key.
        Checks environment variables first, then persistent auth database.
        Fails closed (returns None if invalid).
        """
        if not key:
            return None

        # 1. Check environment variables
        env_roles = [
            ("DASHBOARD_KEY", ROLE_ADMIN),
            ("ADMIN_KEY", ROLE_ADMIN),
            ("APPROVER_KEY", ROLE_APPROVER),
            ("OPERATOR_KEY", ROLE_OPERATOR),
            ("VIEWER_KEY", ROLE_VIEWER),
        ]
        for env_var, role in env_roles:
            val = os.environ.get(env_var, "").strip()
            if val and secrets.compare_digest(val, key):
                return role

        # 2. Check auth database
        data = self._load_auth()
        key_hash = hashlib.sha256(key.encode()).hexdigest()

        # Check explicit roles map
        roles_map = data.get("roles") or {}
        if key_hash in roles_map:
            return roles_map[key_hash].get("role")

        # Backwards compatibility: default dashboard_key_hash is admin
        expected_admin = data.get("dashboard_key_hash", "")
        if expected_admin and secrets.compare_digest(expected_admin, key_hash):
            return ROLE_ADMIN

        return None

    @classmethod
    def has_permission(cls, user_role: Optional[str], required_role: str) -> bool:
        """
        Verify if a user's role satisfies the required permission level.
        Hierarchy: viewer (1) < operator (2) < approver (3) < admin (4).
        """
        if not user_role:
            return False
        user_level = ROLE_HIERARCHY.get(user_role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 999)
        return user_level >= required_level

    def validate_dashboard_key(self, key: str) -> bool:
        """Validate a dashboard API key. Fails closed."""
        return self.get_role_for_key(key) is not None

    def validate_telemetry_key(self, key: str) -> bool:
        """Validate a telemetry ingestion API key. Fails closed."""
        if not key:
            return False
        env_key = os.environ.get("FLEET_KEY", "").strip()
        if env_key and secrets.compare_digest(env_key, key):
            return True

        data = self._load_auth()
        if not data.get('initialized'):
            return False
        expected = data.get('telemetry_key_hash', '')
        if not expected:
            return False
        provided = hashlib.sha256(key.encode()).hexdigest()
        return secrets.compare_digest(expected, provided)

