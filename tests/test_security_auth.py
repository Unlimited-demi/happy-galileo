"""
Security and authentication unit tests for ARA / ServerGuard dashboard and devctl.
"""
import json
import secrets
import pytest
from pathlib import Path
from devctl.core.auth import AuthManager

def test_auth_manager_fail_closed(tmp_path):
    """AuthManager must reject all keys and never allow unauthenticated access when uninitialized."""
    auth_file = tmp_path / "auth.json"
    auth_mgr = AuthManager(auth_file=auth_file)
    
    # 1. Uninitialized state must return False
    assert auth_mgr.validate_dashboard_key("any-random-key") is False
    assert auth_mgr.validate_dashboard_key("") is False
    assert auth_mgr.validate_telemetry_key("any-telemetry-key") is False
    assert auth_mgr.validate_telemetry_key("") is False

def test_auth_manager_initialized_validation(tmp_path):
    """AuthManager must strictly validate sha256 key matches with constant time comparison."""
    auth_file = tmp_path / "auth.json"
    auth_mgr = AuthManager(auth_file=auth_file)
    
    keys = auth_mgr.setup_keys()
    d_key = keys["dashboard_key"]
    t_key = keys["telemetry_key"]
    
    assert d_key != "***"
    assert t_key != "***"
    
    # Valid keys match
    assert auth_mgr.validate_dashboard_key(d_key) is True
    assert auth_mgr.validate_telemetry_key(t_key) is True
    
    # Invalid keys fail
    assert auth_mgr.validate_dashboard_key("wrong_key") is False
    assert auth_mgr.validate_telemetry_key("wrong_key") is False
    assert auth_mgr.validate_dashboard_key("") is False
