"""
Incident Throttling & Contextual Analysis for AI-Ops.
Prevents incident spam by tracking error frequency and patterns per service.
"""

import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import json


class IncidentThrottle:
    """
    Tracks incidents per service and applies throttling rules:
    - Max 1 incident per service per 5 minutes for same error type
    - Escalating severity if errors persist or worsen
    - Contextual analysis: transient vs persistent vs escalating
    """

    THROTTLE_WINDOW_SECONDS = 300  # 5 minutes
    MAX_INCIDENTS_PER_WINDOW = 1
    PERSISTENT_THRESHOLD = 3  # 3+ incidents = persistent
    ESCALATION_THRESHOLD = 5  # 5+ incidents = escalating

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_file = state_dir / "incident_throttle.json"
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load throttle state from disk."""
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"services": {}}

    def _save_state(self):
        """Save throttle state to disk."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[throttle] Error saving state: {e}")

    def should_create_incident(
        self,
        service_name: str,
        error_category: str,
        severity: str = "warning"
    ) -> Tuple[bool, str, str]:
        """
        Determine if an incident should be created based on throttling rules.

        Returns:
            (should_create, context_type, adjusted_severity)
            - context_type: "transient", "persistent", or "escalating"
            - adjusted_severity: may be upgraded based on context
        """
        current_time = time.time()
        service_key = service_name.lower()

        # Initialize service tracking
        if service_key not in self.state["services"]:
            self.state["services"][service_key] = {
                "incidents": [],
                "error_types": {},
            }

        service_state = self.state["services"][service_key]

        # Clean old incidents (outside throttle window)
        window_start = current_time - self.THROTTLE_WINDOW_SECONDS
        service_state["incidents"] = [
            inc for inc in service_state["incidents"]
            if inc["timestamp"] > window_start
        ]

        # Track this error type
        error_key = error_category.lower()
        if error_key not in service_state["error_types"]:
            service_state["error_types"][error_key] = {
                "count": 0,
                "first_seen": current_time,
                "last_seen": current_time,
            }

        error_state = service_state["error_types"][error_key]
        error_state["count"] += 1
        error_state["last_seen"] = current_time

        # Count incidents in current window
        incidents_in_window = len(service_state["incidents"])

        # Contextual Analysis
        context_type = "transient"
        adjusted_severity = severity

        # Check if this is a persistent error (same error type recurring)
        if error_state["count"] >= self.PERSISTENT_THRESHOLD:
            context_type = "persistent"
            # Upgrade severity for persistent errors
            if severity == "warning":
                adjusted_severity = "error"
            elif severity == "error":
                adjusted_severity = "critical"

        # Check if errors are escalating (many incidents in window)
        if incidents_in_window >= self.ESCALATION_THRESHOLD:
            context_type = "escalating"
            # Upgrade to critical for escalating errors
            adjusted_severity = "critical"

        # Throttle check: allow if under limit OR if severity upgraded
        if incidents_in_window < self.MAX_INCIDENTS_PER_WINDOW:
            # Under throttle limit, allow
            should_create = True
        elif context_type in ("persistent", "escalating"):
            # Allow escalated incidents even if over throttle
            should_create = True
        else:
            # Throttled
            should_create = False

        # Record this incident if creating
        if should_create:
            service_state["incidents"].append({
                "timestamp": current_time,
                "error_category": error_category,
                "severity": adjusted_severity,
                "context": context_type,
            })

        # Save state
        self._save_state()

        return should_create, context_type, adjusted_severity

    def get_service_stats(self, service_name: str) -> Dict[str, Any]:
        """Get incident statistics for a service."""
        service_key = service_name.lower()
        if service_key not in self.state["services"]:
            return {"total_incidents": 0, "error_types": {}}

        service_state = self.state["services"][service_key]
        current_time = time.time()
        window_start = current_time - self.THROTTLE_WINDOW_SECONDS

        # Count recent incidents
        recent_incidents = [
            inc for inc in service_state["incidents"]
            if inc["timestamp"] > window_start
        ]

        return {
            "total_incidents": len(service_state["incidents"]),
            "recent_incidents": len(recent_incidents),
            "error_types": service_state["error_types"],
            "throttle_window_seconds": self.THROTTLE_WINDOW_SECONDS,
        }

    def reset_service(self, service_name: str):
        """Reset throttle state for a service (e.g., after resolution)."""
        service_key = service_name.lower()
        if service_key in self.state["services"]:
            del self.state["services"][service_key]
            self._save_state()
