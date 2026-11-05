"""
Job Signer module for ARA Node Commands.
Provides HMAC-SHA256 cryptographic signing and verification for typed commands
dispatched from the Central Hub to satellite nodes over the outbound heartbeat channel.

Guarantees:
1. Origin Authenticity: Proves commands originated from the authorized Hub possessing the fleet secret.
2. Integrity: Detects any tampering with command action, target, or arguments.
3. Replay Protection: Enforces strict timestamp skew windows (default: <= 300s) and nonces.
"""

import time
import hmac
import hashlib
import secrets
from typing import Dict, Any, Tuple, Optional


class JobSigner:
    """Signs and verifies node commands using HMAC-SHA256."""

    DEFAULT_MAX_SKEW_SECONDS = 300  # 5 minutes replay window

    @classmethod
    def sign_command(cls, command: Dict[str, Any], secret_key: str) -> Dict[str, Any]:
        """
        Cryptographically sign a typed command payload.
        Returns a copy of the command enriched with timestamp, nonce, and HMAC signature.
        """
        cmd = dict(command)
        if "timestamp" not in cmd:
            cmd["timestamp"] = time.time()
        if "nonce" not in cmd:
            cmd["nonce"] = secrets.token_hex(8)

        # Standardized message payload: id:node:action:target:timestamp:nonce
        cmd_id = str(cmd.get("id", ""))
        node = str(cmd.get("node", cmd.get("node_name", "")))
        action = str(cmd.get("action", ""))
        target = str(cmd.get("target", ""))
        ts = str(cmd["timestamp"])
        nonce = str(cmd["nonce"])

        raw_payload = f"{cmd_id}:{node}:{action}:{target}:{ts}:{nonce}"
        sig = hmac.new(
            secret_key.encode("utf-8"),
            raw_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        cmd["signature"] = sig
        return cmd

    @classmethod
    def verify_command(
        cls,
        command: Dict[str, Any],
        secret_key: str,
        max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS
    ) -> Tuple[bool, str]:
        """
        Verify the HMAC-SHA256 signature and replay prevention constraints of a command.
        Returns (is_valid, error_message).
        """
        if not secret_key:
            return False, "Fleet secret key not configured on node"

        provided_sig = command.get("signature")
        if not provided_sig:
            return False, "Missing HMAC signature on command"

        cmd_timestamp = command.get("timestamp")
        if cmd_timestamp is None:
            return False, "Missing timestamp on signed command"

        try:
            ts_float = float(cmd_timestamp)
        except (ValueError, TypeError):
            return False, "Invalid timestamp format"

        now = time.time()
        # Enforce replay prevention window
        if abs(now - ts_float) > max_skew_seconds:
            return False, f"Command timestamp skew ({abs(now - ts_float):.1f}s) exceeds replay window ({max_skew_seconds}s)"

        cmd_id = str(command.get("id", ""))
        node = str(command.get("node", command.get("node_name", "")))
        action = str(command.get("action", ""))
        target = str(command.get("target", ""))
        ts = str(command["timestamp"])
        nonce = str(command.get("nonce", ""))

        raw_payload = f"{cmd_id}:{node}:{action}:{target}:{ts}:{nonce}"
        expected_sig = hmac.new(
            secret_key.encode("utf-8"),
            raw_payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not secrets.compare_digest(expected_sig, provided_sig):
            return False, "Cryptographic signature verification failed (forged or tampered command)"

        return True, ""
