"""
Unit tests for JobSigner and Node Command Cryptographic Verification.
Verifies HMAC-SHA256 signatures, tampering detection, and replay prevention.
"""

import time
import pytest
from ai_ops.job_signer import JobSigner
from ai_ops.telemetry import FleetTelemetryStreamer
from unittest.mock import MagicMock, patch


class TestJobSigner:
    SECRET_KEY = "super-secret-fleet-key-12345"

    def test_sign_and_verify_valid_command(self):
        """A properly signed command within timestamp skew window must verify successfully."""
        cmd = {
            "id": "cmd-001",
            "node": "vm-02",
            "action": "restart_container",
            "target": "frontend",
        }
        signed = JobSigner.sign_command(cmd, self.SECRET_KEY)
        assert "signature" in signed
        assert "timestamp" in signed
        assert "nonce" in signed

        is_valid, err = JobSigner.verify_command(signed, self.SECRET_KEY)
        assert is_valid is True
        assert err == ""

    def test_tampered_command_fails_verification(self):
        """Modifying action or target after signing must invalidate HMAC signature."""
        cmd = {
            "id": "cmd-002",
            "node": "vm-02",
            "action": "restart_container",
            "target": "frontend",
        }
        signed = JobSigner.sign_command(cmd, self.SECRET_KEY)
        
        # Tamper with target
        signed["target"] = "production-database"
        is_valid, err = JobSigner.verify_command(signed, self.SECRET_KEY)
        assert is_valid is False
        assert "forged or tampered" in err

    def test_wrong_secret_key_fails(self):
        """Signing with one secret and verifying with another must fail."""
        cmd = {"id": "cmd-003", "node": "vm-02", "action": "restart_container", "target": "worker"}
        signed = JobSigner.sign_command(cmd, self.SECRET_KEY)

        is_valid, err = JobSigner.verify_command(signed, "attacker-secret-key")
        assert is_valid is False
        assert "forged or tampered" in err

    def test_replay_attack_rejected_on_stale_timestamp(self):
        """Commands older than max skew window must be rejected."""
        cmd = {"id": "cmd-004", "node": "vm-02", "action": "purge_incidents", "target": ""}
        signed = JobSigner.sign_command(cmd, self.SECRET_KEY)
        
        # Simulate replay 600 seconds later (beyond 300s window)
        signed["timestamp"] = time.time() - 600
        # Recompute signature for the old timestamp to test timestamp freshness check specifically
        signed = JobSigner.sign_command(signed, self.SECRET_KEY)

        is_valid, err = JobSigner.verify_command(signed, self.SECRET_KEY, max_skew_seconds=300)
        assert is_valid is False
        assert "exceeds replay window" in err

    def test_telemetry_streamer_rejects_unsigned_command(self):
        """Node streamer must reject executing unsigned commands."""
        streamer = FleetTelemetryStreamer(fleet_key=self.SECRET_KEY)
        unsigned_cmd = {
            "id": "cmd-005",
            "action": "restart_container",
            "target": "web",
        }
        res = streamer._execute_command(unsigned_cmd)
        assert res["success"] is False
        assert "Cryptographic verification rejected" in res["error"]

    def test_telemetry_streamer_blocks_database_mutation(self):
        """Node streamer must reject commands attempting to resync or expose sealed databases."""
        streamer = FleetTelemetryStreamer(fleet_key=self.SECRET_KEY)
        cmd = {
            "id": "cmd-006",
            "node": "node-01",
            "action": "resync_network",
            "target": "postgres-db",
        }
        signed = JobSigner.sign_command(cmd, self.SECRET_KEY)

        with patch("devctl.core.docker_mgr.DockerManager.is_database_or_cache") as mock_db:
            mock_db.return_value = (True, "PostgreSQL database (port 5432)")
            res = streamer._execute_command(signed)
            assert res["success"] is False
            assert "sealed PostgreSQL database" in res["error"]
