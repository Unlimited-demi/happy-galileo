"""
Unit & Integration tests for devctl core modules.
"""

import pytest
from pathlib import Path
from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from devctl.core.caddy import CaddyManager
from devctl.core.incident_bus import IncidentBus, IncidentState


def test_domain_formatting():
    """Verify domain generator with wildcard *.dev-server.datakrib.com."""
    assert Config.get_full_domain("vessel-api", "dev") == "vessel-api.dev-server.datakrib.com"
    assert Config.get_full_domain("vessel-api", "staging") == "vessel-api-staging.dev-server.datakrib.com"
    assert Config.get_full_domain("vessel-api", "prod") == "vessel-api-prod.dev-server.datakrib.com"
    assert Config.get_full_domain("frontend") == "frontend.dev-server.datakrib.com"


def test_slug_sanitization():
    """Verify slug sanitization for DNS compatibility."""
    assert DomainRegistry.sanitize_slug("My Super Service 123!") == "my-super-service-123"
    assert DomainRegistry.sanitize_slug("---feature_branch---") == "feature-branch"
    assert DomainRegistry.sanitize_slug("vessel.api") == "vessel-api"


def test_domain_registry_persistence(tmp_path):
    """Verify registration, state persistence, and retrieval."""
    state_file = tmp_path / "state.json"
    registry = DomainRegistry(state_file=state_file)

    # Register service
    entry = registry.register(
        service_name="test-app",
        container_name="test-app-container",
        port=3000,
        domain="test-app.dev-server.datakrib.com",
        env="dev",
    )

    assert entry["service_name"] == "test-app"
    assert entry["url"] == "https://test-app.dev-server.datakrib.com"

    # Reload from disk
    new_reg = DomainRegistry(state_file=state_file)
    svc = new_reg.get_service("test-app")
    assert svc is not None
    assert svc["port"] == 3000

    # Unregister
    new_reg.unregister("test-app")
    assert new_reg.get_service("test-app") is None


def test_incident_lifecycle(tmp_path):
    """Verify incident creation, claiming, dossier generation, and resolution."""
    incidents_dir = tmp_path / "incidents"
    bus = IncidentBus(incidents_dir=incidents_dir)

    # 1. Create incident
    inc = bus.create_incident(
        service_name="payment-api",
        title="HTTP 500 on /checkout route",
        severity="HIGH",
        level=3,
        evidence={
            "status_code": 500,
            "failing_url": "https://payment-api.dev-server.datakrib.com/checkout",
            "stack_trace": "TypeError: Cannot read properties of undefined at Checkout.process()",
        },
    )

    inc_id = inc["id"]
    assert inc_id.startswith("INC-")
    assert inc["state"] == IncidentState.DETECTED

    # Verify markdown dossier was generated
    md_path = incidents_dir / f"{inc_id}.md"
    assert md_path.exists()
    md_content = md_path.read_text(encoding="utf-8")
    assert "Incident Dossier" in md_content
    assert "Checkout.process()" in md_content

    # 2. Claim by OpenCode
    claimed = bus.claim_incident(inc_id, agent_name="OpenCode")
    assert claimed["state"] == IncidentState.CLAIMED
    assert claimed["claimed_by"] == "OpenCode"

    # 3. Resolve
    resolved = bus.resolve_incident(inc_id, notes="Fixed null check in checkout controller.")
    assert resolved["state"] == IncidentState.RESOLVED
    assert resolved["resolution_notes"] == "Fixed null check in checkout controller."
