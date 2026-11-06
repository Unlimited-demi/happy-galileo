"""
Concert (Collab) Webhook Dispatcher for ARA.
Sends authenticated, structured incident cards and resolution proof to Concert
team channels (#infrastructure / #devops) for automated thread spawning and ChatOps.
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from ai_ops.brain import BrainEngine


class ConcertNotifier:
    """Dispatches ARA incidents to Concert team incoming webhooks."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        self.webhook_url = webhook_url or os.environ.get("CONCERT_WEBHOOK_URL", "")
        self.webhook_secret = webhook_secret or os.environ.get("CONCERT_WEBHOOK_SECRET", "")
        self.brain = BrainEngine()

    def send_incident_alert(
        self,
        incident: Dict[str, Any],
        occurrences: int = 1,
        node_name: Optional[str] = None,
        rollback_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synthesize incident explanation via BrainEngine and post formatted card to Concert.
        """
        if not self.webhook_url:
            return {"sent": False, "reason": "CONCERT_WEBHOOK_URL not configured"}

        service_name = incident.get("service_name", "app")
        severity = incident.get("severity", "HIGH")
        title = incident.get("title", f"Failure detected on {service_name}")
        evidence = incident.get("evidence", {}) or {}
        error_logs = evidence.get("error_message") or evidence.get("logs") or title
        error_category = evidence.get("error_category", "runtime_failure")

        # 1. Generate 2-sentence plain-English explanation via Local Brain
        summary = self.brain.explain_incident(
            service_name=service_name,
            error_category=error_category,
            error_logs=str(error_logs),
            context={"severity": severity, "occurrences": occurrences}
        )

        # 2. Build structured payload for Concert
        payload = {
            "incident_id": incident.get("id"),
            "fingerprint": incident.get("fingerprint"),
            "service_name": service_name,
            "node_name": node_name or os.environ.get("NODE_NAME", "vm-01"),
            "severity": severity,
            "title": title,
            "plain_english_summary": summary,
            "status": incident.get("state", "DETECTED"),
            "occurrences": occurrences,
            "rollback_id": rollback_id,
            "pr_url": incident.get("pr_url"),
            "recommended_action": incident.get("recommended_action") or "Automated remediation evaluated under Level 1 Playbook.",
        }

        # 3. Post to Concert incoming webhook
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ARA-Fleet-Agent/2.0",
            "X-Tenant-Id": os.environ.get("CONCERT_TENANT_ID", "suburban"),
            "X-Tenant-ID": os.environ.get("CONCERT_TENANT_ID", "suburban"),
        }
        if self.webhook_secret:
            headers["X-Webhook-Secret"] = self.webhook_secret

        try:
            req = urllib.request.Request(self.webhook_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                success = resp.status in (200, 201, 202)
                return {
                    "sent": success,
                    "status_code": resp.status,
                    "payload": payload,
                }
        except Exception as e:
            return {
                "sent": False,
                "error": str(e),
                "payload": payload,
            }

    def send_chatops_reply(
        self,
        reply_text: str,
        query: str = "",
        thread_context: Optional[Dict[str, Any]] = None,
        engine: str = "ara-brain",
    ) -> Dict[str, Any]:
        """
        Post an asynchronous ChatOps response back to the Concert team channel or thread.
        """
        if not self.webhook_url:
            return {"sent": False, "reason": "CONCERT_WEBHOOK_URL not configured"}

        context = thread_context or {}
        thread_id = (
            context.get("thread_id")
            or context.get("threadId")
            or context.get("conversation_id")
            or context.get("parent_id")
            or context.get("id")
        )
        channel_id = context.get("channel_id") or context.get("channelId")
        user_id = (
            context.get("user_id")
            or context.get("sender_id")
            or context.get("author")
            or context.get("userId")
        )

        import time
        import secrets
        inc_id = context.get("incident_id") or f"INC-{time.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

        payload = {
            "incident_id": inc_id,
            "fingerprint": "N/A",
            "service_name": context.get("service_name") or "Core System",
            "node_name": os.environ.get("NODE_NAME", "hub-vm"),
            "severity": "INFO",
            "title": "ARA Autonomous SRE Response",
            "plain_english_summary": reply_text,
            "text": reply_text,
            "content": reply_text,
            "message": reply_text,
            "sender": "ARA (Autonomous SRE)",
            "query": query,
            "engine": engine,
            "status": "COMPLETED",
            "occurrences": 1,
            "recommended_action": "Reply with @ARA <question> to consult the AI assistant.",
        }
        if thread_id:
            payload["thread_id"] = thread_id
            payload["threadId"] = thread_id
            payload["parent_id"] = thread_id
            payload["conversation_id"] = thread_id
        if channel_id:
            payload["channel_id"] = channel_id
            payload["channelId"] = channel_id
        if user_id:
            payload["user_id"] = user_id
            payload["mention"] = user_id

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ARA-Fleet-Agent/2.0",
            "X-Tenant-Id": os.environ.get("CONCERT_TENANT_ID", "suburban"),
            "X-Tenant-ID": os.environ.get("CONCERT_TENANT_ID", "suburban"),
        }
        if self.webhook_secret:
            headers["X-Webhook-Secret"] = self.webhook_secret

        try:
            req = urllib.request.Request(self.webhook_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                success = resp.status in (200, 201, 202)
                return {
                    "sent": success,
                    "status_code": resp.status,
                    "payload": payload,
                }
        except Exception as e:
            return {
                "sent": False,
                "error": str(e),
                "payload": payload,
            }
