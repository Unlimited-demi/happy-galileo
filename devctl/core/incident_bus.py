"""
Incident Bus module for devctl.
Tracks, stores, and manages incidents and handoffs between AI-Ops and OpenCode.
"""

import json
import hashlib
import threading
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
    RESOLVED = "RESOLVED"
    RESOLVED_UNVERIFIED = "RESOLVED_UNVERIFIED"
    VERIFIED = "VERIFIED"
    MERGED = "MERGED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class IncidentBus:
    """Manages structured incidents, dossiers, and lifecycle state."""

    def __init__(self, incidents_dir: Optional[Path] = None):
        self.incidents_dir = incidents_dir or Config.INCIDENTS_DIR
        self.incidents_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def compute_fingerprint(
        service_name: str,
        error_category: str = "",
        error_signature: str = ""
    ) -> str:
        """Compute a deterministic hash for deduplicating identical service errors."""
        raw = f"{service_name.strip().lower()}:{error_category.strip().lower()}:{error_signature.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def find_by_fingerprint(self, fingerprint: str, only_open: bool = True) -> Optional[Dict[str, Any]]:
        """Find an existing incident by its error fingerprint."""
        if not fingerprint:
            return None
        incidents = self.list_incidents(only_open=only_open)
        for inc in incidents:
            if inc.get("fingerprint") == fingerprint:
                return inc
        return None

    def record_occurrence(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Increment occurrence counter and refresh updated_at timestamp."""
        with self._lock:
            incident = self.get_incident(incident_id)
            if not incident:
                return None
            incident["occurrences"] = incident.get("occurrences", 1) + 1
            incident["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.save_incident(incident)
            return incident

    def create_incident(
        self,
        service_name: str,
        title: str,
        severity: str = "HIGH",  # LOW, MEDIUM, HIGH, CRITICAL
        level: int = 3,  # Level 1-3
        evidence: Optional[Dict[str, Any]] = None,
        recommendation: Optional[str] = None,
        fingerprint: Optional[str] = None,
        occurrences: int = 1,
        source_node: str = "hub-vm",
    ) -> Dict[str, Any]:
        """Create and persist a new incident dossier."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        short_id = uuid.uuid4().hex[:6].upper()
        incident_id = f"INC-{date_str}-{short_id}"

        if not fingerprint:
            fingerprint = self.compute_fingerprint(service_name, severity, title)

        incident = {
            "id": incident_id,
            "service_name": service_name,
            "source_node": source_node or "hub-vm",
            "title": title,
            "severity": severity,
            "level": level,
            "state": IncidentState.DETECTED,
            "fingerprint": fingerprint,
            "occurrences": occurrences,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "claimed_by": None,
            "resolved_at": None,
            "resolution_notes": None,
            "evidence": evidence or {},
            "recommendation": recommendation,
        }

        # Save JSON (locked for concurrent safety)
        json_path = self.incidents_dir / f"{incident_id}.json"
        with self._lock:
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

        proof = incident.get("resolution_proof", {})
        resolution_notes = incident.get("resolution_notes", "")
        resolved_at = incident.get("resolved_at", "")

        resolution_section = ""
        if incident["state"] in [IncidentState.RESOLVED, IncidentState.RESOLVED_UNVERIFIED, IncidentState.VERIFIED, IncidentState.MERGED, IncidentState.FAILED, IncidentState.CLOSED]:
            is_verified = incident["state"] in (IncidentState.VERIFIED, IncidentState.MERGED)
            status_label = "VERIFIED & RESOLVED" if incident["state"] == IncidentState.VERIFIED else incident["state"]
            resolution_section = f"""
---

## {'✅' if is_verified else '⚠️'} Resolution & Verification Proof
- **Status:** `{status_label}`
- **Resolved By:** `{incident.get('claimed_by', 'N/A')}`
- **Resolved At:** `{resolved_at or 'N/A'}`
- **Deployment URL:** `{proof.get('live_url', failing_url)}`
- **Health Probe:** `{proof.get('health_probe', 'N/A')}`
- **Container State:** `{proof.get('container_state', 'N/A')}`
- **Git Branch:** `{proof.get('git_branch', 'N/A')}`
- **Git Commit:** `{proof.get('git_commit', 'N/A')}`
- **Git Push Status:** `{proof.get('git_push_status', 'N/A')}`

### 📝 Remediation & Root Cause Insight:
{resolution_notes or 'No remediation notes recorded.'}

### 🛠️ Code Diff & Files Modified:
```text
{proof.get('git_diff', 'No git diff recorded.')}
```
"""

        content = f"""# 🚨 Incident Dossier: {incident_id}
**Service:** `{incident['service_name']}`  
**Severity:** `{incident['severity']}` | **Level:** `{incident['level']}`  
**State:** `{incident['state']}`  
**Fingerprint:** `{incident.get('fingerprint', 'N/A')}` | **Occurrences:** {incident.get('occurrences', 1)}  
**Detected At:** `{incident['created_at']}`  

---

## 📌 Summary
{incident['title']}

## 🔍 Diagnostic Evidence
- **Container State:** `{evidence.get('container_state', 'Unknown')}`
- **HTTP Status:** `{status_code}`
- **Failing URL:** `{failing_url}`
- **Stack / Project Type:** `{evidence.get('project_type', 'Docker Service')}`

## 📁 Codebase & Git Context
- **Workspace Directory:** `{evidence.get('workspace_dir', 'N/A')}`
- **Docker Compose File:** `{evidence.get('compose_file', 'N/A')}`
- **Target Compose Service:** `{evidence.get('compose_service', incident['service_name'])}`
- **Active Git Branch:** `{evidence.get('git_branch', 'master')}`
- **Recent Git Commit:** `{evidence.get('git_commit', 'N/A')}`

### 🪵 Recent Logs / Stack Trace:
```text
{stack_trace if stack_trace != 'None' else logs}
```

## 🛠️ Recommended Action for OpenCode
{incident.get('recommendation', 'Investigate recent code changes, run regression tests, fix application bug, and redeploy.')}

### 📋 Suggested Autonomous Remediation Workflow:
```bash
# 1. Navigate to service workspace
cd {evidence.get('workspace_dir', '/opt/happy-galileo')}

# 2. Checkout fix branch
git checkout -b fix/{incident['service_name']}-{incident_id.lower()}

# 3. Implement code fix & rebuild container
docker compose up -d --build {evidence.get('compose_service', incident['service_name'])}

# 4. Deploy staging verification route & test with Playwright
devctl expose {incident['service_name']} {evidence.get('port', 80)} --env staging
devctl test {incident['service_name']}-staging

# 5. Mark incident resolved
devctl incident resolve {incident_id} --notes "Resolved {incident['service_name']} root cause and verified on staging."
```
{resolution_section}
---
*To inspect dossier: `devctl incident inspect {incident_id}`*
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
            with self._lock:
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
        with self._lock:
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

    def resolve_incident(self, incident_id: str, notes: str = "", proof: Optional[Dict[str, Any]] = None, verified: bool = False) -> Optional[Dict[str, Any]]:
        """Mark incident as resolved with honest verification proof."""
        state = IncidentState.VERIFIED if verified else IncidentState.RESOLVED_UNVERIFIED
        return self.update_incident(
            incident_id,
            {
                "state": state,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
                "resolution_notes": notes,
                "resolution_proof": proof or {},
            },
        )

    def save_incident(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Save an entire incident dictionary directly."""
        incident_id = incident["id"]
        incident["updated_at"] = datetime.now(timezone.utc).isoformat()
        json_path = self.incidents_dir / f"{incident_id}.json"
        with self._lock:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(incident, f, indent=2)
            self._write_markdown_dossier(incident)
        return incident

    def list_incidents(self, only_open: bool = False) -> List[Dict[str, Any]]:
        """List all incidents."""
        incidents = []
        with self._lock:
            for file in self.incidents_dir.glob("INC-*.json"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        inc = json.load(f)
                        if only_open and inc.get("state") in [
                            IncidentState.RESOLVED,
                            IncidentState.RESOLVED_UNVERIFIED,
                            IncidentState.CLOSED,
                            IncidentState.VERIFIED,
                            IncidentState.MERGED,
                        ]:
                            continue
                        incidents.append(inc)
                except Exception:
                    continue
        # Sort newest first
        incidents.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return incidents

    def purge_all_incidents(self) -> int:
        """Delete all incident files. Returns count of deleted incidents."""
        count = 0
        with self._lock:
            for file in self.incidents_dir.glob("INC-*"):
                try:
                    file.unlink()
                    count += 1
                except Exception:
                    pass
        return count
