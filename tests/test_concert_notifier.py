"""
Unit tests for ConcertNotifier.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from ai_ops.concert_notifier import ConcertNotifier


class TestConcertNotifier:
    def test_send_alert_without_url(self):
        """Should fail cleanly when webhook URL is not configured."""
        notifier = ConcertNotifier(webhook_url="")
        res = notifier.send_incident_alert({"id": "INC-001"})
        assert res["sent"] is False
        assert "not configured" in res["reason"]

    def test_send_alert_success(self):
        """Should construct structured alert card and post to Concert webhook."""
        notifier = ConcertNotifier(
            webhook_url="https://api-collab.suburban.ng/api/v1/webhooks/teams/team-123/incoming",
            webhook_secret="secret_abc_123"
        )
        incident = {
            "id": "INC-999",
            "fingerprint": "a3f89c02d18e",
            "service_name": "edge-proxy",
            "severity": "CRITICAL",
            "title": "502 Bad Gateway",
            "evidence": {
                "error_message": "502 Bad Gateway from upstream edge",
                "error_category": "ingress_502"
            }
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            res = notifier.send_incident_alert(incident, occurrences=2, node_name="vm-02")
            assert res["sent"] is True
            assert res["status_code"] == 200

            payload = res["payload"]
            assert payload["incident_id"] == "INC-999"
            assert payload["fingerprint"] == "a3f89c02d18e"
            assert payload["node_name"] == "vm-02"
            assert payload["occurrences"] == 2
            assert "plain_english_summary" in payload
            assert len(payload["plain_english_summary"]) > 0
