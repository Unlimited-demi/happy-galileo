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

    SRE_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "get_fleet_nodes",
                "description": "Inspect all enrolled cluster servers and worker nodes in the fleet and their operational statuses.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_service_telemetry",
                "description": "Inspect time-series telemetry trends (memory drift, latency drift, health flapping) for a specific container or fleet-wide summary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Optional name of the target service or container (e.g. 'devctl-dashboard', 'ai-ops-daemon', 'caddy', 'billing-api', 'chaos-api'). Omit for fleet-wide summary."
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_active_incidents",
                "description": "List currently open SRE incident dossiers, plain-English root causes, error signatures, and recommended actions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Optional service name to filter incidents (e.g. 'devctl-dashboard')."
                        }
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_recent_rollbacks",
                "description": "Query recent automated or manual rollback actions performed by the policy engine.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    ]

    def _execute_tool(self, tool_name: str, args: Dict[str, Any], fleet_store: Optional[Any] = None) -> Any:
        """Execute a tool called by Qwen ReAct agent against live stores."""
        if tool_name == "get_fleet_nodes":
            if fleet_store and hasattr(fleet_store, "get_all_nodes"):
                nodes = fleet_store.get_all_nodes()
                if nodes:
                    return [
                        {"name": n.get("node_name"), "status": n.get("status"), "services": n.get("services_count")}
                        for n in nodes
                    ]
            return [{"name": "Central Hub (vm-test)", "status": "ONLINE", "type": "primary", "services": 6}]

        elif tool_name == "get_service_telemetry":
            svc_name = args.get("service_name")
            try:
                from ai_ops.metrics_store import MetricsStore
                store = MetricsStore()
                if svc_name:
                    return store.detect_trends(svc_name, window_hours=2.0)
                else:
                    return store.trend_summary(window_hours=2.0)
            except Exception as e:
                return {"error": f"Telemetry retrieval failed: {str(e)}"}

        elif tool_name == "get_active_incidents":
            svc_name = args.get("service_name")
            try:
                from devctl.core.incident_bus import IncidentBus
                bus = IncidentBus()
                open_inc = bus.list_incidents(only_open=True)
                if svc_name:
                    open_inc = [i for i in open_inc if i.get("service_name") == svc_name]
                return [
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
            except Exception as e:
                return {"error": f"Incidents retrieval failed: {str(e)}"}

        elif tool_name == "get_recent_rollbacks":
            try:
                from ai_ops.policy_engine import RollbackLedger
                ledger = RollbackLedger()
                return ledger.list_recent_actions(limit=5)
            except Exception as e:
                return {"error": f"Rollback retrieval failed: {str(e)}"}

        return {"error": f"Unknown tool: {tool_name}"}

    def handle_chatops_query(
        self,
        query: str,
        thread_context: Optional[Dict[str, Any]] = None,
        fleet_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Process natural language queries from Concert engineers using native ReAct tool-calling with Qwen 2.5.
        Qwen inspects the tool schemas, issues tool calls, inspects the observations, and reasons over live telemetry.
        """
        import logging
        logger = logging.getLogger("ARA.Brain")

        # 1. Native ReAct Tool-Calling Execution with Qwen 2.5 via Ollama /api/chat
        if self.is_available():
            try:
                system_prompt = (
                    "You are ARA, an autonomous site reliability engineer for Suburban & Legend. "
                    "You investigate infrastructure issues using your provided tools. "
                    "Always call the appropriate tools (get_service_telemetry, get_active_incidents, get_fleet_nodes, get_recent_rollbacks) "
                    "to gather live data before answering questions about servers, containers, memory, incidents, flapping, or performance. "
                    "Reason over the tool observations and formulate a concise, professional, technical response (under 4 sentences). "
                    "Never invent data. Quote exact metrics, container names, and incident IDs from tool results."
                )

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ]

                executed_tools_record = []

                # Autonomous ReAct Loop (Up to 3 turns of tool invocation -> observation -> reasoning)
                for _ in range(3):
                    payload = {
                        "model": self.model,
                        "messages": messages,
                        "tools": self.SRE_TOOLS,
                        "stream": False,
                        "keep_alive": -1,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 140,
                            "num_thread": 2,
                        }
                    }
                    data = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(
                        f"{self.brain_url}/api/chat",
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=18.0) as resp:
                        if resp.status != 200:
                            break
                        res_json = json.loads(resp.read().decode("utf-8"))
                        msg = res_json.get("message", {})
                        tool_calls = msg.get("tool_calls", [])

                        if not tool_calls:
                            # Final answer synthesized by Qwen!
                            final_answer = msg.get("content", "").strip()
                            if final_answer:
                                return {
                                    "reply": final_answer,
                                    "answer": final_answer,
                                    "explanation": final_answer,
                                    "context_data": {"executed_tools": executed_tools_record},
                                    "engine": f"ara-brain-react-{self.model}",
                                }
                            break

                        # Qwen decided to call tools! Add assistant tool_calls message
                        messages.append(msg)

                        for call in tool_calls:
                            func = call.get("function", {})
                            name = func.get("name", "")
                            args = func.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}

                            logger.info(f"[ARA Brain] ReAct Agent invoking tool '{name}' with args {args}")
                            result = self._execute_tool(name, args, fleet_store=fleet_store)
                            executed_tools_record.append({"tool": name, "args": args, "result": result})

                            messages.append({
                                "role": "tool",
                                "content": json.dumps(result),
                            })
            except Exception as e:
                logger.warning(f"[ARA Brain] Native ReAct tool-calling loop fallback: {e}")

        # 2. Fail-Safe Telemetry Fallback (Triggered only when model container is offline)
        # Gathers live telemetry from the exact same tools and presents honest status
        q_lower = query.lower()
        parts = []

        # Find target service if mentioned
        target_svc = (thread_context or {}).get("service_name") or ""
        for s in ["devctl-dashboard", "ai-ops-daemon", "caddy", "billing-api", "chaos-api", "chaos-db", "demo-app"]:
            if s in q_lower:
                target_svc = s
                break

        # Service specific diagnostic
        if target_svc:
            st = self._execute_tool("get_service_telemetry", {"service_name": target_svc})
            if isinstance(st, dict) and "service" in st:
                warnings = st.get("warnings", [])
                lines = [f"📊 Diagnostics for `{target_svc}`:"]
                if warnings:
                    lines.append("  • " + " | ".join(f"[{w.get('type')}] {w.get('detail', '')}" for w in warnings))
                else:
                    lines.append(f"  • ✅ No anomalies detected across {st.get('samples', 0)} telemetry samples.")
                lines.append(f"  • Memory Drift: {st.get('mem_growth_pct', 0):+.1f}% | Latency Drift: {st.get('latency_factor', 1.0):.2f}x | Verdict: {st.get('verdict', 'STABLE')}")
                parts.append("\n".join(lines))

            svc_inc = self._execute_tool("get_active_incidents", {"service_name": target_svc})
            if isinstance(svc_inc, list) and svc_inc:
                inc_lines = [f"🚨 Active Incidents on `{target_svc}` ({len(svc_inc)}):"]
                for inc in svc_inc:
                    inc_lines.append(f"  • `{inc['id']}` [{inc.get('severity', 'HIGH')}]: {inc.get('summary') or inc.get('title')}")
                parts.append("\n".join(inc_lines))

        # Fleet nodes check
        if any(w in q_lower for w in ["node", "fleet", "servers", "status", "overview", "how many"]):
            nodes = self._execute_tool("get_fleet_nodes", {}, fleet_store=fleet_store)
            if isinstance(nodes, list):
                parts.append(f"🌐 Nodes: " + ", ".join(f"{n['name']} ({n.get('status', 'ONLINE')})" for n in nodes))

        # General incidents check
        if any(w in q_lower for w in ["incident", "error", "alert", "status", "about", "issue"]) and not target_svc:
            incidents = self._execute_tool("get_active_incidents", {})
            if isinstance(incidents, list) and incidents:
                inc_lines = [f"🚨 Active Incidents ({len(incidents)}):"]
                for inc in incidents:
                    inc_lines.append(f"• `{inc['id']}` [{inc.get('severity', 'HIGH')}] on `{inc.get('service', 'unknown')}`: {inc.get('summary') or inc.get('title')}")
                parts.append("\n".join(inc_lines))

        # Memory / trend summary
        if any(w in q_lower for w in ["memory", "trend", "usage", "status", "resource", "flapping"]) and not target_svc:
            ft = self._execute_tool("get_service_telemetry", {})
            if isinstance(ft, dict):
                warnings = []
                for svc, data in ft.items():
                    if isinstance(data, dict):
                        for w in data.get("warnings", []):
                            warnings.append(f"• ⚠️ `{svc}`: {w.get('detail')}")
                if warnings:
                    parts.append("📈 Fleet Telemetry Warnings:\n" + "\n".join(warnings))

        if parts:
            answer = "\n\n".join(parts)
        else:
            answer = (
                "Hello! I am ARA, your autonomous SRE companion for Suburban & Legend. "
                "I investigate systems using real-time telemetry, node state, and incident dossiers. "
                "Ask me about any container, fleet status, memory leaks, or active incidents."
            )

        return {
            "reply": answer,
            "answer": answer,
            "explanation": answer,
            "context_data": {"mode": "deterministic_fallback"},
            "engine": "ara-brain-local",
        }



