"""
Unit tests for RBAC (Role-Based Access Control) in AuthManager and Hub API.
"""

import pytest
from unittest.mock import MagicMock, patch
from devctl.core.auth import (
    AuthManager,
    ROLE_VIEWER,
    ROLE_OPERATOR,
    ROLE_APPROVER,
    ROLE_ADMIN,
)


class TestRBACAuth:
    def test_role_hierarchy_permissions(self):
        """Verify role hierarchy: viewer < operator < approver < admin."""
        # Admin has permission for all roles
        assert AuthManager.has_permission(ROLE_ADMIN, ROLE_VIEWER) is True
        assert AuthManager.has_permission(ROLE_ADMIN, ROLE_OPERATOR) is True
        assert AuthManager.has_permission(ROLE_ADMIN, ROLE_APPROVER) is True
        assert AuthManager.has_permission(ROLE_ADMIN, ROLE_ADMIN) is True

        # Approver has permission for approver, operator, viewer, but NOT admin
        assert AuthManager.has_permission(ROLE_APPROVER, ROLE_VIEWER) is True
        assert AuthManager.has_permission(ROLE_APPROVER, ROLE_OPERATOR) is True
        assert AuthManager.has_permission(ROLE_APPROVER, ROLE_APPROVER) is True
        assert AuthManager.has_permission(ROLE_APPROVER, ROLE_ADMIN) is False

        # Operator has permission for operator, viewer, but NOT approver or admin
        assert AuthManager.has_permission(ROLE_OPERATOR, ROLE_VIEWER) is True
        assert AuthManager.has_permission(ROLE_OPERATOR, ROLE_OPERATOR) is True
        assert AuthManager.has_permission(ROLE_OPERATOR, ROLE_APPROVER) is False
        assert AuthManager.has_permission(ROLE_OPERATOR, ROLE_ADMIN) is False

        # Viewer only has permission for viewer
        assert AuthManager.has_permission(ROLE_VIEWER, ROLE_VIEWER) is True
        assert AuthManager.has_permission(ROLE_VIEWER, ROLE_OPERATOR) is False
        assert AuthManager.has_permission(ROLE_VIEWER, ROLE_APPROVER) is False
        assert AuthManager.has_permission(ROLE_VIEWER, ROLE_ADMIN) is False

        # None or invalid role has no permissions
        assert AuthManager.has_permission(None, ROLE_VIEWER) is False
        assert AuthManager.has_permission("invalid_role", ROLE_VIEWER) is False

    def test_create_and_resolve_role_keys(self, tmp_path):
        """Keys created with specific roles must resolve to that exact role."""
        auth_file = tmp_path / "auth.json"
        auth_mgr = AuthManager(auth_file=auth_file)
        auth_mgr.setup_keys()

        viewer_key = auth_mgr.create_role_key(ROLE_VIEWER, name="Security Auditor")
        operator_key = auth_mgr.create_role_key(ROLE_OPERATOR, name="Ops Engineer")
        approver_key = auth_mgr.create_role_key(ROLE_APPROVER, name="Tech Lead")
        admin_key = auth_mgr.create_role_key(ROLE_ADMIN, name="Cluster Admin")

        assert auth_mgr.get_role_for_key(viewer_key) == ROLE_VIEWER
        assert auth_mgr.get_role_for_key(operator_key) == ROLE_OPERATOR
        assert auth_mgr.get_role_for_key(approver_key) == ROLE_APPROVER
        assert auth_mgr.get_role_for_key(admin_key) == ROLE_ADMIN

        # Non-existent key must return None
        assert auth_mgr.get_role_for_key("fake_random_key") is None

    def test_environment_variable_role_override(self, tmp_path):
        """Keys provided via environment variables (DASHBOARD_KEY, OPERATOR_KEY, etc.) must resolve correctly."""
        auth_file = tmp_path / "auth.json"
        auth_mgr = AuthManager(auth_file=auth_file)

        with patch.dict("os.environ", {
            "DASHBOARD_KEY": "env_admin_secret",
            "OPERATOR_KEY": "env_operator_secret",
            "VIEWER_KEY": "env_viewer_secret",
        }):
            assert auth_mgr.get_role_for_key("env_admin_secret") == ROLE_ADMIN
            assert auth_mgr.get_role_for_key("env_operator_secret") == ROLE_OPERATOR
            assert auth_mgr.get_role_for_key("env_viewer_secret") == ROLE_VIEWER
            assert auth_mgr.get_role_for_key("unknown") is None
