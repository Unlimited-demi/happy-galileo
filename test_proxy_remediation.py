"""Test Level 2 remediation with multiple proxy types (Caddy, Nginx, Apache)."""
import os
import sys
import tempfile

os.environ["DEVCTL_STATE_DIR"] = tempfile.mkdtemp(prefix="devctl_proxy_test_")
sys.path.insert(0, r"C:\Users\Admin\Documents\antigravity\happy-galileo")

failures = []
def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failures.append(name)

from ai_ops.remediation import RemediationEngine

class StubDocker:
    def __init__(self, proxy_name="caddy"):
        self.proxy_name = proxy_name
        self.reconnected = []
        self.execs = []
    def list_containers(self):
        return [{"Names": [f"/{self.proxy_name}"]}]
    def get_networks(self, name):
        return ["bridge"]  # Desync
    def connect_to_network(self, container, network):
        self.reconnected.append((container, network))
        return True
    def exec_in_container(self, name, cmd):
        self.execs.append((name, cmd))
        return True
    def restart_container(self, name):
        return True

import pytest

@pytest.mark.parametrize("proxy_name,expected_cmd", [
    ("caddy", ["caddy", "reload", "--config", "/etc/caddy/Caddyfile"]),
    ("nginx", ["nginx", "-s", "reload"]),
    ("apache", ["apachectl", "graceful"]),
    ("httpd", ["apachectl", "graceful"]),
    ("unknown", None),
])
def test_proxy(proxy_name, expected_cmd):
    engine = RemediationEngine()
    engine.docker = StubDocker(proxy_name=proxy_name)

    health = {
        "service_name": "web", "container_name": "web", "healthy": False,
        "container_running": True, "url": "https://web.example.com",
        "log_error": None, "failure_reasons": ["Docker HEALTHCHECK reports unhealthy"],
        "new_restarts": 0, "oom_killed": False, "docker_health": "unhealthy",
    }

    result = engine.handle_health_result(dict(health))
    assert result.get("level") == 2
    assert engine.docker.reconnected == [("web", "dev-net")]

    if expected_cmd is None:
        assert len(engine.docker.execs) == 0
    elif engine.docker.execs:
        actual_cmd = engine.docker.execs[0][1]
        assert actual_cmd == expected_cmd
    else:
        assert False, "No exec call made"
