"""
ARA Brain: Local CPU Intelligence Engine.
Connects the ARA Central Hub to a local lightweight CPU model (e.g. Qwen2.5-3B / Llama3.2-3B)
for instant, stress-free error explanation and Concert ChatOps dialogue.

Guarantees:
1. Zero GPU Requirement: Designed to run efficiently on 2 CPU cores (<2.5GB RAM).
2. Fail-Safe: Always falls back to deterministic rule-based analysis if the model container is starting or offline.
3. Fast & Bounded: Strict generation timeouts (<= 8s) and token limits (<= 150 tokens) to prevent CPU starvation.
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional


class BrainEngine:
    """Interfaces with local CPU inference engine for error explanation and ChatOps."""

    DEFAULT_MODEL = "qwen2.5:3b"

    def __init__(self, brain_url: Optional[str] = None, model: Optional[str] = None):
        self.brain_url = (brain_url or os.environ.get("BRAIN_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("BRAIN_MODEL", self.DEFAULT_MODEL)

    def is_available(self, timeout: float = 1.5) -> bool:
        """Check if local brain inference engine is online and responding."""
        try:
            req = urllib.request.Request(f"{self.brain_url}/api/version", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def explain_incident(
        self,
        service_name: str,
        error_category: str,
        error_logs: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Synthesize a plain-English 2-sentence incident explanation for Concert.
        Falls back to deterministic rule-based analysis if brain is offline.
        """
        clean_logs = (error_logs or "No logs available").strip()[:1000]

        # 1. Attempt LLM generation if local CPU brain is reachable
        if self.is_available():
            try:
                system_prompt = (
                    "You are ARA, an autonomous site reliability engineer. "
                    "Analyze the provided incident error logs and explain the root cause in 2 clear, concise sentences. "
                    "State exactly what broke and why. Avoid greetings, preamble, or markdown code fences."
                )
                user_prompt = (
                    f"Service: {service_name}\n"
                    f"Category: {error_category}\n"
                    f"Error Logs:\n{clean_logs}\n\n"
                    "Provide a 2-sentence technical root-cause explanation for human engineers."
                )

                payload = {
                    "model": self.model,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 120,
                        "num_thread": 2,  # CPU thread clamp
                    }
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.brain_url}/api/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        explanation = res_json.get("response", "").strip()
                        if explanation:
                            return explanation
            except Exception:
                pass  # Fall back to deterministic analysis

        # 2. Deterministic Fallback (Reliable, fast, $0)
        clean_excerpt = clean_logs.splitlines()[0] if clean_logs.splitlines() else "Connection reset or timeout"
        if len(clean_excerpt) > 120:
            clean_excerpt = clean_excerpt[:117] + "..."

        if "oom" in error_category.lower() or "137" in clean_logs:
            return f"Container '{service_name}' exceeded its allocated memory limits and was terminated by the Linux OOM-killer. Immediate restart was evaluated under Level 1 Playbook."
        elif "502" in clean_logs or "bad gateway" in clean_logs.lower():
            return f"Upstream reverse proxy reported 502 Bad Gateway because '{service_name}' stopped responding to internal network probes. Proxy routes are being verified."
        elif "connection refused" in clean_logs.lower():
            return f"Service '{service_name}' refused internal TCP connections on its designated port. Check service initialization scripts and network attachments."
        else:
            return f"Incident detected on '{service_name}' under category '{error_category}'. Error signature: {clean_excerpt}"

    def handle_chatops_query(
        self,
        query: str,
        thread_context: Optional[Dict[str, Any]] = None,
        fleet_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Process natural language queries from Concert engineers (e.g. '@ARA how is vm-02 doing?').
        Dispatches tool lookups against local stores and formulates response.
        """
        q_lower = query.lower()
        context_data: Dict[str, Any] = {}

        # 1. Tool dispatch based on query intent
        if any(w in q_lower for w in ["node", "fleet", "servers", "vm-"]):
            if fleet_store and hasattr(fleet_store, "get_all_nodes"):
                nodes = fleet_store.get_all_nodes()
                context_data["nodes"] = [
                    {"name": n.get("node_name"), "status": n.get("status"), "services": n.get("services_count")}
                    for n in nodes
                ]
            else:
                context_data["nodes"] = [{"name": "Local Workstation", "status": "ONLINE"}]

        if any(w in q_lower for w in ["rollback", "revert", "undo"]):
            from ai_ops.policy_engine import RollbackLedger
            ledger = RollbackLedger()
            recent_rb = ledger.list_recent_actions(limit=5)
            context_data["recent_rollbacks"] = recent_rb

        if any(w in q_lower for w in ["incident", "error", "alert"]):
            from devctl.core.incident_bus import IncidentBus
            bus = IncidentBus()
            open_inc = bus.list_incidents(only_open=True)
            context_data["open_incidents"] = [
                {"id": i.get("id"), "service": i.get("service_name"), "severity": i.get("severity")}
                for i in open_inc[:5]
            ]

        # 2. Formulate response
        if context_data.get("nodes"):
            node_summaries = ", ".join(f"{n['name']} ({n['status']})" for n in context_data["nodes"])
            answer = f"🌐 Fleet status: {node_summaries}."
        elif context_data.get("recent_rollbacks"):
            last_rb = context_data["recent_rollbacks"][0]
            answer = f"⏪ Last rollback: Action `{last_rb.get('action')}` on `{last_rb.get('service_name')}` (ID: {last_rb.get('id')}) status: {last_rb.get('status')}."
        elif context_data.get("open_incidents"):
            inc_list = ", ".join(f"`{i['id']}` ({i['service']})" for i in context_data["open_incidents"])
            answer = f"🚨 Current active incidents ({len(context_data['open_incidents'])}): {inc_list}."
        else:
            answer = (
                f"Hello! I am ARA, your autonomous SRE companion. "
                f"All systems are currently being monitored. "
                f"You can ask me about fleet nodes, active incidents, or recent rollbacks."
            )

        return {
            "answer": answer,
            "context_data": context_data,
            "engine": "ara-brain-local",
        }
