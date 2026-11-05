"""
Unit tests for Incident Fingerprinting, Deduplication, and Throttling.
Verifies that:
1. Identical service errors generate deterministic fingerprints.
2. Subsequent occurrences of an open incident increment the occurrence counter rather than spamming new dossiers.
3. IncidentThrottle enforces limits per window and escalates severity for persistent errors.
"""

from unittest.mock import MagicMock, patch
import pytest
from devctl.core.incident_bus import IncidentBus
from ai_ops.remediation import RemediationEngine
from ai_ops.incident_throttle import IncidentThrottle


def test_compute_fingerprint():
    fp1 = IncidentBus.compute_fingerprint("web-app", "log_error", "TypeError: Cannot read properties of undefined")
    fp2 = IncidentBus.compute_fingerprint("web-app", "log_error", "TypeError: Cannot read properties of undefined")
    fp3 = IncidentBus.compute_fingerprint("web-app", "oom", "OOM killed (memory exhaustion)")
    fp4 = IncidentBus.compute_fingerprint("api-service", "log_error", "TypeError: Cannot read properties of undefined")

    assert fp1 == fp2, "Identical service errors must produce identical fingerprints"
    assert fp1 != fp3, "Different error categories must produce distinct fingerprints"
    assert fp1 != fp4, "Different services must produce distinct fingerprints"
    assert len(fp1) == 16, "Fingerprint hash should be truncated to 16 hex characters"


def test_find_by_fingerprint_and_record_occurrence(tmp_path):
    bus = IncidentBus(incidents_dir=tmp_path)
    fp = IncidentBus.compute_fingerprint("auth-service", "database", "connection refused")

    inc = bus.create_incident(
        service_name="auth-service",
        title="Database connection refused",
        severity="HIGH",
        fingerprint=fp,
    )
    assert inc["fingerprint"] == fp
    assert inc["occurrences"] == 1

    found = bus.find_by_fingerprint(fp, only_open=True)
    assert found is not None
    assert found["id"] == inc["id"]

    updated = bus.record_occurrence(inc["id"])
    assert updated["occurrences"] == 2

    reloaded = bus.get_incident(inc["id"])
    assert reloaded["occurrences"] == 2


@patch("ai_ops.remediation.DockerSocket")
def test_remediation_dedup_and_occurrence_tracking(mock_docker_cls, tmp_path):
    mock_docker_cls.return_value.get_networks.return_value = ["dev-net"]
    engine = RemediationEngine()
    engine.incident_bus.incidents_dir = tmp_path
    engine.incident_bus.incidents_dir.mkdir(parents=True, exist_ok=True)

    health_payload = {
        "service_name": "payments-api",
        "healthy": False,
        "container_running": True,
        "log_error": "ConnectionRefusedError: Redis on port 6379 unavailable",
        "failure_reasons": ["HTTP check failed"],
    }

    # First occurrence -> Creates new incident
    res1 = engine.handle_health_result(health_payload)
    assert res1["action"] in ["ESCALATE_TO_OPENCODE", "ESCALATE_AND_DISPATCH"]
    inc_id = res1["incident_id"]

    inc1 = engine.incident_bus.get_incident(inc_id)
    assert inc1["occurrences"] == 1

    # Second occurrence -> Deduplicated, increments occurrence count, returns ALREADY_REPORTED
    res2 = engine.handle_health_result(health_payload)
    assert res2["action"] == "ALREADY_REPORTED"
    assert res2["service"] == "payments-api"

    inc2 = engine.incident_bus.get_incident(inc_id)
    assert inc2["occurrences"] == 2


def test_incident_throttle_window_and_escalation(tmp_path):
    throttle = IncidentThrottle(state_dir=tmp_path)

    # 1. First error -> should create, transient, warning
    should_create, ctx, sev = throttle.should_create_incident("billing", "timeout", severity="warning")
    assert should_create is True
    assert ctx == "transient"
    assert sev == "warning"

    # 2. Second error in same window -> throttled (limit is 1 per window)
    should_create, ctx, sev = throttle.should_create_incident("billing", "timeout", severity="warning")
    assert should_create is False

    # 3. Third error -> persistent threshold reached -> allows creation with escalated severity "error"
    should_create, ctx, sev = throttle.should_create_incident("billing", "timeout", severity="warning")
    assert should_create is True
    assert ctx == "persistent"
    assert sev == "error"

    # 4. Reset service after recovery
    throttle.reset_service("billing")
    stats = throttle.get_service_stats("billing")
    assert stats["total_incidents"] == 0
