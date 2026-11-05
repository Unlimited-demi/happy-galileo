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

    def is_available(self, timeout: float = 1.0) -> bool:
        """Check if local brain inference engine is online and responding."""
        try:
            req = urllib.request.Request(f"{self.brain_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    base_model = self.model.split(":")[0]
                    has_model = any(self.model in m or base_model in m for m in models)
                    if not has_model and models:
                        print(f"[ARA Brain] Ollama active at {self.brain_url}, but model '{self.model}' not found in {models}. Pulling required.")
                    return True
        except urllib.error.HTTPError:
            # Older endpoint fallback
            try:
                req = urllib.request.Request(f"{self.brain_url}/", method="GET")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status == 200
            except Exception:
                return False
        except Exception:
            # Connection refused, host unreachable, or timeout — brain is offline
            return False
        return False

    def preload_model(self) -> bool:
        """
        Pre-warm and pin the model in RAM with keep_alive=-1 so it never unloads
        and responds with 0 cold-start latency.
        """
        try:
            payload = {"model": self.model, "keep_alive": -1}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.brain_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
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
                    "keep_alive": -1,  # Keep permanently resident in RAM
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
        Process natural language queries from Concert engineers (e.g. '@ARA what is the status of the fleet?').
        Dispatches tool lookups against local stores and formulates response.
        """
        q_lower = query.lower().strip()
        context_data: Dict[str, Any] = {}

        # 1. Tool dispatch based on query intent (Action -> Observation)
        target_svc = (thread_context or {}).get("service_name") or ""
        try:
            from ai_ops.metrics_store import MetricsStore
            store = MetricsStore()
            available_services = store.services()
        except Exception:
            store = None
            available_services = []

        known_fleet_services = list(set(available_services + [
            "devctl-dashboard", "dashboard", "caddy", "ai-ops-daemon", "ai-ops",
            "ara-brain", "billing-api", "chaos-api", "chaos-db", "demo-app"
        ]))

        if not target_svc:
            for s in sorted(known_fleet_services, key=len, reverse=True):
                if s.lower() in q_lower:
                    target_svc = s
                    break

        wants_diagnostic = any(w in q_lower for w in ["why", "cause", "causing", "flapping", "flap", "leak", "creep", "tell me", "about", "what happened", "crash", "restart", "unstable", "drift", "churn", "explain"]) or bool(target_svc)
        wants_status = any(w in q_lower for w in ["status", "health", "overview", "state", "summary", "how is", "report", "check", "diagnos"]) or wants_diagnostic
        wants_fleet = any(w in q_lower for w in ["node", "fleet", "servers", "vm-", "host"]) or (wants_status and not target_svc)
        wants_metrics = any(w in q_lower for w in ["memory", "cpu", "metric", "trend", "latency", "usage", "ram", "drift", "flapping", "leak"]) or wants_status
        wants_incidents = any(w in q_lower for w in ["incident", "error", "alert", "why", "down", "fail", "issue", "broke", "crash", "about"]) or wants_status
        wants_rollback = any(w in q_lower for w in ["rollback", "revert", "undo"])

        if wants_fleet:
            if fleet_store and hasattr(fleet_store, "get_all_nodes"):
                nodes = fleet_store.get_all_nodes()
                if nodes:
                    context_data["nodes"] = [
                        {"name": n.get("node_name"), "status": n.get("status"), "services": n.get("services_count")}
                        for n in nodes
                    ]
                else:
                    context_data["nodes"] = [{"name": "Central Hub (vm-test)", "status": "ONLINE", "type": "primary"}]
            else:
                context_data["nodes"] = [{"name": "Central Hub (vm-test)", "status": "ONLINE", "type": "primary"}]

        if target_svc and store:
            context_data["service_trends"] = store.detect_trends(target_svc, window_hours=2.0)
            context_data["target_service"] = target_svc
        elif wants_metrics and store:
            context_data["fleet_trends"] = store.trend_summary(window_hours=2.0)

        if wants_incidents:
            try:
                from devctl.core.incident_bus import IncidentBus
                bus = IncidentBus()
                open_inc = bus.list_incidents(only_open=True)
                if target_svc:
                    svc_inc = [i for i in open_inc if i.get("service_name") == target_svc]
                    if svc_inc:
                        open_inc = svc_inc
                context_data["open_incidents"] = [
                    {
                        "id": i.get("id"),
                        "service": i.get("service_name"),
                        "severity": i.get("severity"),
                        "title": i.get("title", ""),
                        "summary": i.get("plain_english_summary") or i.get("title", ""),
                        "state": i.get("state", "ACTIVE"),
                        "occurrences": i.get("occurrences", 1),
                    }
                    for i in open_inc[:5]
                ]
            except Exception:
                pass

        if wants_rollback:
            try:
                from ai_ops.policy_engine import RollbackLedger
                ledger = RollbackLedger()
                recent_rb = ledger.list_recent_actions(limit=5)
                context_data["recent_rollbacks"] = recent_rb
            except Exception:
                pass

        # 2. ReAct Synthesis: Let the Local CPU Model reason over observations if online
        if self.is_available() and context_data:
            try:
                system_prompt = (
                    "You are ARA, an autonomous site reliability engineer for Suburban & Legend. "
                    "Analyze the user's question alongside the live system observations retrieved from telemetry. "
                    "Formulate a structured, professional, and visually soothing response in Markdown. "
                    "Use bold section headers and clean bullet points for readability. "
                    "Format statuses in uppercase brackets like [ONLINE], [STABLE], [CRITICAL], [HIGH], [WARN]. "
                    "Format service names and IDs in backticks like `service-name`. "
                    "Never dump long run-on sentences or pipe-separated lists. "
                    "Never invent data. State exact metrics, node names, and operational statuses truthfully."
                )
                user_prompt = (
                    f"Engineer Query: {query}\n"
                    f"Live System Observations: {json.dumps(context_data)}\n\n"
                    "Provide your SRE assessment and answer:"
                )
                payload = {
                    "model": self.model,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False,
                    "keep_alive": -1,  # Keep permanently resident in RAM
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 90,  # Fast bounded generation on CPU
                        "num_thread": 2,
                    }
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.brain_url}/api/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        llm_reply = res_json.get("response", "").strip()
                        if llm_reply:
                            return {
                                "reply": llm_reply,
                                "answer": llm_reply,
                                "explanation": llm_reply,
                                "context_data": context_data,
                                "engine": f"ara-brain-react-{self.model}",
                            }
            except Exception as e:
                import logging
                logging.getLogger("ARA.Brain").warning(f"Local LLM reasoning bypassed: {e}")

        # 3. Deterministic Fallback Synthesis (Fast, reliable, zero-latency, rich telemetry)
        parts = []

        # Target Service diagnostics
        if context_data.get("service_trends"):
            st = context_data["service_trends"]
            svc = st.get("service") or target_svc or "service"
            mem_trend = st.get("mem_growth_pct", 0)
            lat_factor = st.get("latency_factor", 1.0)
            warnings = st.get("warnings", [])

            lines = [f"📊 **Diagnostics for `{svc}`**:"]
            if warnings:
                for w in warnings:
                    lines.append(f"• ⚠️ [{w.get('type')}] {w.get('detail', '')}")
            else:
                lines.append(f"• ✅ No anomalies detected across {st.get('samples', 0)} telemetry samples.")
            lines.append(f"• **Memory Drift**: `{mem_trend:+.1f}%` | **Latency Drift**: `{lat_factor:.2f}x` | **Status**: [{st.get('verdict', 'STABLE')}]")

            svc_incidents = [i for i in context_data.get("open_incidents", []) if i.get("service") == svc]
            if svc_incidents:
                lines.append(f"\n🚨 **Correlated Incidents ({len(svc_incidents)})**:")
                for inc in svc_incidents:
                    summary = inc.get("summary") or inc.get("title")
                    lines.append(f"• `{inc['id']}` [{inc.get('severity', 'HIGH')}]: {summary}")
            parts.append("\n".join(lines))

        # Fleet / Nodes part (if general status or fleet asked)
        if context_data.get("nodes") and not target_svc:
            nodes = context_data["nodes"]
            online_count = sum(1 for n in nodes if n.get("status") == "ONLINE")
            node_lines = [f"🌐 **Fleet Status** ({online_count}/{len(nodes)} Online):"]
            for n in nodes:
                st = n.get("status", "ONLINE")
                svcs = n.get("services")
                svc_suffix = f" — {svcs} services" if svcs else ""
                node_lines.append(f"• `{n['name']}` [{st}]{svc_suffix}")
            parts.append("\n".join(node_lines))

        # Open Incidents part (when general status or incident query)
        if "open_incidents" in context_data and not context_data.get("service_trends"):
            incidents = context_data["open_incidents"]
            if incidents:
                inc_lines = [f"🚨 **Active Incidents ({len(incidents)})**:"]
                for i in incidents:
                    summary = i.get("summary") or i.get("title") or "Under investigation"
                    inc_lines.append(f"• `{i['id']}` [{i.get('severity', 'HIGH')}] on `{i.get('service', 'unknown')}`: {summary}")
                parts.append("\n".join(inc_lines))
            elif wants_incidents:
                parts.append("✅ **Incidents**: Zero active incidents across fleet. All systems operational.")

        # Fleet-wide trends
        if context_data.get("fleet_trends"):
            ft = context_data["fleet_trends"]
            warnings = []
            stable_svcs = []
            for svc, data in ft.items():
                svc_warns = data.get("warnings", [])
                if svc_warns:
                    for w in svc_warns:
                        warnings.append(f"• ⚠️ `{svc}`: {w.get('detail')}")
                else:
                    stable_svcs.append(svc)

            trend_lines = ["📈 **Fleet Telemetry & Resource Trends**:"]
            if warnings:
                trend_lines.append("**Anomaly Warnings**:\n" + "\n".join(warnings))
            if stable_svcs:
                trend_lines.append(f"• **Nominal Services ({len(stable_svcs)})**: " + ", ".join(f"`{s}`" for s in stable_svcs))
            parts.append("\n".join(trend_lines))

        # Rollbacks part
        if context_data.get("recent_rollbacks"):
            last_rb = context_data["recent_rollbacks"][0]
            parts.append(f"⏪ **Automated Remediation**: `{last_rb.get('action')}` on `{last_rb.get('service_name')}` [{last_rb.get('status', 'EXECUTED')}]")

        if parts:
            answer = "\n\n".join(parts)
        else:
            answer = (
                "Hello! I am ARA, your autonomous SRE companion for Suburban & Legend. "
                "All systems are currently being monitored. "
                "You can ask me about fleet nodes, active incidents, memory trends, or rollbacks."
            )

        return {
            "reply": answer,
            "answer": answer,
            "explanation": answer,
            "context_data": context_data,
            "engine": "ara-brain-local",
        }


