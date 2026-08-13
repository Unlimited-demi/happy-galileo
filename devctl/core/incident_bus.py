"""
Incident Bus module for devctl.
Tracks, stores, and manages incidents and handoffs between AI-Ops and OpenCode.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from .config import Config


class IncidentState:
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    CLAIMED = "CLAIMED"
    FIXED = "FIXED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


class IncidentBus:
    """Manages structured incidents, dossiers, and lifecycle state."""

    def __init__(self, incidents_dir: Optional[Path] = None):
        self.incidents_dir = incidents_dir or Config.INCIDENTS_DIR
        self.incidents_dir.mkdir(parents=True, exist_ok=True)

    def create_incident(
        self,
        service_name: str,
        title: str,
        severity: str = "HIGH",  # LOW, MEDIUM, HIGH, CRITICAL
        level: int = 3,  # Level 1-3
        evidence: Optional[Dict[str, Any]] = None,
        recommendation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and persist a new incident dossier."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        short_id = uuid.uuid4().hex[:6].upper()
        incident_id = f"INC-{date_str}-{short_id}"

        incident = {
            "id": incident_id,
            "service_name": service_name,
            "title": title,
            "severity": severity,
            "level": level,
            "state": IncidentState.DETECTED,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "claimed_by": None,
            "resolved_at": None,
            "resolution_notes": None,
            "evidence": evidence or {},
            "recommendation": recommendation,
        }

        # Save JSON
        json_path = self.incidents_dir / f"{incident_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(incident, f, indent=2)

        # Save Markdown dossier
        self._write_markdown_dossier(incident)

        return incident

    def _write_markdown_dossier(self, incident: Dict[str, Any]) -> Path:
        """Render a readable Markdown Incident Dossier for OpenCode."""
        incident_id = incident["id"]
        md_path = self.incidents_dir / f"{incident_id}.md"

        evidence = incident.get("evidence", {})
        logs = evidence.get("logs", "No logs provided.")
        stack_trace = evidence.get("stack_trace", "None")
        failing_url = evidence.get("failing_url", "N/A")
        status_code = evidence.get("status_code", "N/A")

        content = f"""# 🚨 Incident Dossier: {incident_id}
**Service:** `{incident['service_name']}`  
**Severity:** `{incident['severity']}` | **Level:** `{incident['level']}`  
**State:** `{incident['state']}`  
**Detected At:** `{incident['created_at']}`  

---

## 📌 Summary
{incident['title']}

## 🔍 Evidence
- **Failing URL:** `{failing_url}`
- **HTTP Status:** `{status_code}`
- **Container State:** `{evidence.get('container_state', 'Unknown')}`
- **Recent Git Commit:** `{evidence.get('git_commit', 'N/A')}`

### 🪵 Recent Logs / Stack Trace:
```text
{stack_trace if stack_trace != 'None' else logs}
```

## 🛠️ Recommended Action for OpenCode
{incident.get('recommendation', 'Investigate recent code changes, run regression tests, fix application bug, and redeploy.')}

---
*To claim this incident, run: `devctl incident claim {incident_id}`*  
*To mark resolved, run: `devctl incident resolve {incident_id} --notes "Fixed root cause"`*
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)

        return md_path

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Fetch incident data by ID."""
        json_path = self.incidents_dir / f"{incident_id}.json"
        if not json_path.exists():
            return None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def update_incident(self, incident_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update incident fields and re-render markdown."""
        incident = self.get_incident(incident_id)
        if not incident:
            return None

        incident.update(updates)
        incident["updated_at"] = datetime.now(timezone.utc).isoformat()

        json_path = self.incidents_dir / f"{incident_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(incident, f, indent=2)

        self._write_markdown_dossier(incident)
        return incident

    def claim_incident(self, incident_id: str, agent_name: str = "OpenCode") -> Optional[Dict[str, Any]]:
        """Mark incident as claimed by an agent."""
        return self.update_incident(
            incident_id,
            {"state": IncidentState.CLAIMED, "claimed_by": agent_name},
        )

    def resolve_incident(self, incident_id: str, notes: str = "") -> Optional[Dict[str, Any]]:
        """Mark incident as resolved."""
        return self.update_incident(
            incident_id,
            {
                "state": IncidentState.RESOLVED,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "resolution_notes": notes,
            },
        )

    def list_incidents(self, only_open: bool = False) -> List[Dict[str, Any]]:
        """List all incidents."""
        incidents = []
        for file in self.incidents_dir.glob("INC-*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    inc = json.load(f)
                    if only_open and inc.get("state") in [IncidentState.RESOLVED, IncidentState.CLOSED]:
                        continue
                    incidents.append(inc)
            except Exception:
                continue
        # Sort newest first
        incidents.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return incidents
