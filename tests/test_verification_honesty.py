"""
Tests for Honest Verification Engine and State Integrity.
Validates that incidents cannot fabricate VERIFIED status when health probes fail or containers are stopped.
"""

import pytest
import tempfile
from pathlib import Path
from devctl.core.incident_bus import IncidentBus, IncidentState


@pytest.fixture
def temp_incident_bus():
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = IncidentBus(incidents_dir=Path(tmpdir))
        yield bus


def test_incident_state_lifecycle(temp_incident_bus):
    bus = temp_incident_bus
    
    # 1. Create incident -> state should be DETECTED
    inc = bus.create_incident(
        service_name="frontend",
        title="Frontend 502 Bad Gateway",
        severity="HIGH",
        evidence={"status_code": 502, "container_state": "restarting"}
    )
    assert inc["state"] == IncidentState.DETECTED
    incident_id = inc["id"]

    # 2. Claim incident -> state should be CLAIMED
    claimed = bus.claim_incident(incident_id, agent_name="OpenCode")
    assert claimed["state"] == IncidentState.CLAIMED
    assert claimed["claimed_by"] == "OpenCode"

    # 3. Resolve incident with unverified proof (e.g. probe failed or stopped) -> state must be RESOLVED_UNVERIFIED
    unverified_res = bus.resolve_incident(
        incident_id,
        notes="Attempted fix but probe timed out",
        proof={
            "container_state": "STOPPED",
            "health_probe": "Failed: Connection Refused",
            "live_url": "https://frontend.dev-server.datakrib.com",
        },
        verified=False
    )
    assert unverified_res["state"] == IncidentState.RESOLVED_UNVERIFIED
    assert unverified_res["state"] != IncidentState.VERIFIED

    # Verify dossier markdown does NOT label it as VERIFIED & RESOLVED
    md_file = bus.incidents_dir / f"{incident_id}.md"
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "RESOLVED_UNVERIFIED" in content
    assert "VERIFIED & RESOLVED" not in content

    # 4. Resolve incident with verified proof (probe HTTP 200 and running) -> state is VERIFIED
    verified_res = bus.resolve_incident(
        incident_id,
        notes="Fixed upstream config and confirmed HTTP 200",
        proof={
            "container_state": "RUNNING",
            "health_probe": "HTTP 200 OK (22ms)",
            "live_url": "https://frontend.dev-server.datakrib.com",
        },
        verified=True
    )
    assert verified_res["state"] == IncidentState.VERIFIED
    
    # Verify markdown reflects VERIFIED & RESOLVED
    content_verified = md_file.read_text(encoding="utf-8")
    assert "VERIFIED & RESOLVED" in content_verified


def test_list_incidents_filtering(temp_incident_bus):
    bus = temp_incident_bus
    
    inc1 = bus.create_incident(service_name="app1", title="Issue 1")
    inc2 = bus.create_incident(service_name="app2", title="Issue 2")
    
    # Initially 2 open
    assert len(bus.list_incidents(only_open=True)) == 2

    # Resolve inc1 as unverified -> both VERIFIED and RESOLVED_UNVERIFIED are excluded from open
    bus.resolve_incident(inc1["id"], notes="done", verified=False)
    open_incs = bus.list_incidents(only_open=True)
    assert len(open_incs) == 1
    assert open_incs[0]["id"] == inc2["id"]

    # All includes both
    all_incs = bus.list_incidents(only_open=False)
    assert len(all_incs) == 2


def test_save_incident_direct(temp_incident_bus):
    bus = temp_incident_bus
    inc = bus.create_incident(service_name="api", title="API Timeout")
    
    inc["state"] = IncidentState.MERGED
    inc["merge_commit"] = "a1b2c3d"
    bus.save_incident(inc)

    reloaded = bus.get_incident(inc["id"])
    assert reloaded["state"] == IncidentState.MERGED
    assert reloaded["merge_commit"] == "a1b2c3d"
