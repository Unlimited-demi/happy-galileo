import pytest
from pathlib import Path
import tempfile
from ai_ops.flight_recorder import FlightRecorder


def test_flight_recorder_generate():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        fr = FlightRecorder(incidents_dir=tmp_path)

        incident = {
            "id": "INC-TEST-001",
            "service_name": "test-service",
            "source_node": "test-node",
            "state": "RESOLVED",
            "severity": "CRITICAL",
            "fingerprint": "abc12345",
            "evidence": {
                "issue_type": "FATAL_ERROR",
                "logs": "FATAL: connection timeout",
            },
            "recommendation": "Service failed due to connection timeout.",
            "resolution_notes": "Restarted service and verified network.",
            "resolution_proof": {
                "health_probe": "HTTP 200 OK",
                "container_state": "RUNNING",
            }
        }

        record = fr.get_or_generate_flight_record(incident)
        assert record is not None
        assert record["incident_id"] == "INC-TEST-001"
        assert record["status"] == "COMPLETED"
        assert len(record["timeline"]) >= 4

        # Verify steps
        step_phases = [s["phase"] for s in record["timeline"]]
        assert "TELEMETRY INGESTION" in step_phases
        assert "AI-OPS REASONING (QWEN 2.5)" in step_phases
        assert "REMEDIATION EXECUTION" in step_phases
        assert "VERIFIED & RESOLVED" in step_phases


def test_flight_recorder_append_step():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        fr = FlightRecorder(incidents_dir=tmp_path)

        rec = fr.append_step(
            incident_id="INC-TEST-002",
            phase="TEST_PHASE",
            title="Custom Execution Step",
            agent_thought="Testing step append",
            command="echo hello",
            stdout="hello\n",
            status="success"
        )

        assert rec["total_steps"] == 1
        assert rec["timeline"][0]["command"] == "echo hello"
        assert rec["timeline"][0]["stdout"] == "hello\n"
