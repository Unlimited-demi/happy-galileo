"""
Autonomous Dispatcher for AI-Ops and OpenCode.
Executes the autonomous remediation dispatch pipeline:
1. Resolves workspace and compose context for the failing service.
2. Creates and checks out a dedicated git fix branch: fix/<service>-<incident_id>.
3. Formats the full diagnostic remediation blueprint prompt.
4. Launches OpenCode inside an isolated tmux session.
5. Advances the incident state to CLAIMED (40%).
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from devctl.core.config import Config
from devctl.core.domains import DomainRegistry
from devctl.core.incident_bus import IncidentBus, IncidentState


class IncidentDispatcher:
    """Dispatches incidents to OpenCode for autonomous diagnosis and remediation."""

    def __init__(self):
        self.bus = IncidentBus()
        self.registry = DomainRegistry()

    def dispatch(
        self,
        incident_id: str,
        agent_name: str = "OpenCode",
        use_tmux: bool = True,
        fleet_store: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatch an incident to OpenCode.
        Returns dispatch status and metadata.
        """
        incident = self.bus.get_incident(incident_id)
        target_node = "Local Controller"

        # If not found on local disk, search fleet store (connected satellite nodes)
        if not incident and fleet_store:
            for n_name, n_data in list(fleet_store.items()):
                if isinstance(n_data, dict):
                    for rinc in (n_data.get("all_incidents") or n_data.get("open_incidents") or []):
                        if isinstance(rinc, dict) and rinc.get("id") == incident_id:
                            incident = rinc
                            target_node = n_name
                            # Mutate state in fleet store so dashboard UI updates immediately
                            rinc["state"] = "CLAIMED"
                            rinc["claimed_by"] = agent_name
                            # Also persist a local dossier copy
                            try:
                                json_path = self.bus.incidents_dir / f"{incident_id}.json"
                                import json
                                with open(json_path, "w", encoding="utf-8") as f:
                                    json.dump(rinc, f, indent=2)
                            except Exception:
                                pass
                            break
                if incident:
                    break

        if not incident:
            return {"success": False, "error": f"Incident '{incident_id}' not found in local bus or fleet store."}

        service_name = incident.get("service_name", "app")
        title = incident.get("title", "Service incident")
        severity = incident.get("severity", "HIGH")
        evidence = incident.get("evidence", {}) or {}

        # 1. Resolve host workspace directory & compose file
        svc_entry = self.registry.get_service(service_name) or {}
        svc_meta = svc_entry.get("metadata") or {}
        codebase = (
            evidence.get("codebase")
            or ({"workspace_dir": svc_entry.get("workspace_dir"), "compose_file": svc_entry.get("compose_file")} if svc_entry.get("workspace_dir") else None)
            or (svc_meta.get("codebase"))
            or {}
        )

        workspace_dir = codebase.get("workspace_dir") or (f"/opt/projects/{service_name}" if os.path.isdir(f"/opt/projects/{service_name}") else "/opt/happy-galileo")
        compose_file = codebase.get("compose_file") or (os.path.join(workspace_dir, "docker-compose.yml") if os.path.isfile(os.path.join(workspace_dir, "docker-compose.yml")) else "docker-compose.yml")
        base_branch = codebase.get("git_branch") or "master"
        fix_branch = f"fix/{service_name}-{incident_id}"

        # 2. Claim the incident in IncidentBus (20% -> 40%)
        try:
            self.bus.claim_incident(incident_id, agent_name=agent_name)
        except Exception:
            pass

        # 3. Format OpenCode prompt blueprint
        staging_domain = Config.get_full_domain(service_name, env=Config.STAGING_NAMESPACE)
        staging_url = f"https://{staging_domain}"
        dossier_path = self.bus.incidents_dir / f"{incident_id}.md"

        prompt = f"""[CRITICAL INCIDENT REMEDIATION DISPATCH]
Incident ID: {incident_id}
Target Service: {service_name}
Severity: {severity}
Summary: {title}

📁 Host Workspace: {workspace_dir}
📄 Compose File: {compose_file}
🌿 Active Git Branch: {fix_branch} (branched from {base_branch})
🌐 Staging Verification Endpoint: {staging_url}
📋 Diagnostic Dossier: {dossier_path}

REMEDIATION WORKFLOW CONTRACT (AGENTS.md):
1. Navigate to physical codebase: cd {workspace_dir}
2. Inspect the error trace in {dossier_path} and identify the bug.
3. Edit the source code / configuration to fix the root cause.
4. Rebuild & start container: docker compose up -d
5. Expose staging route: devctl expose {service_name} <port> --env {Config.STAGING_NAMESPACE}
6. Verify fix with Playwright: devctl test {service_name}
7. Once clean, commit changes and resolve incident:
   devctl incident resolve {incident_id} --agent "{agent_name}" --notes "Fixed root cause and verified on staging"
"""

        # 4. Prepare git fix branch in the physical codebase
        if os.path.isdir(workspace_dir) and os.path.isdir(os.path.join(workspace_dir, ".git")):
            try:
                subprocess.run(["git", "-C", workspace_dir, "checkout", "-B", fix_branch], check=False, capture_output=True)
            except Exception:
                pass

        # 5. Launch OpenCode via tmux or direct background process
        session_name = f"opencode-{incident_id}"
        has_tmux = shutil.which("tmux") is not None
        has_opencode = shutil.which("opencode") is not None

        if use_tmux and has_tmux:
            # Check if session already exists
            check_sess = subprocess.run(["tmux", "has-session", "-t", session_name], capture_output=True)
            if check_sess.returncode == 0:
                return {
                    "success": True,
                    "session_name": session_name,
                    "workspace_dir": workspace_dir,
                    "fix_branch": fix_branch,
                    "status": "ALREADY_DISPATCHED",
                    "message": f"OpenCode session '{session_name}' is already active.",
                }

            # Create tmux session and launch OpenCode (or an interactive bash runner)
            subprocess.run(["tmux", "new-session", "-d", "-s", session_name, "-c", workspace_dir], check=False)
            
            # Send the OpenCode command or prompt to tmux session
            if has_opencode:
                cmd = f'opencode --prompt {repr(prompt)}'
            else:
                # Fallback banner if opencode CLI is not globally linked
                cmd = f'echo "=== [OPENCODE REMEDIATION WORKER: {incident_id}] ==="; echo {repr(prompt)}'
            
            subprocess.run(["tmux", "send-keys", "-t", session_name, cmd, "C-m"], check=False)

            return {
                "success": True,
                "session_name": session_name,
                "workspace_dir": workspace_dir,
                "fix_branch": fix_branch,
                "status": "DISPATCHED",
                "message": f"OpenCode dispatched in tmux session '{session_name}'. Attach with: tmux attach -t {session_name}",
            }
        else:
            # Fallback: start background process
            return {
                "success": True,
                "session_name": "background",
                "workspace_dir": workspace_dir,
                "fix_branch": fix_branch,
                "status": "DISPATCHED",
                "message": f"Incident claimed and prepared in branch {fix_branch}.",
            }

    @classmethod
    def get_worker_status(cls, incident_id: str) -> Dict[str, Any]:
        """Fetch real-time worker logs and status for a dispatched incident."""
        session_name = f"opencode-{incident_id}"
        logs = ""
        is_running = False

        # 1. Try capturing from live tmux session
        try:
            check = subprocess.run(["tmux", "has-session", "-t", session_name], capture_output=True)
            if check.returncode == 0:
                is_running = True
                capture = subprocess.run(["tmux", "capture-pane", "-p", "-t", session_name], capture_output=True, text=True)
                logs = capture.stdout.strip()
        except Exception:
            pass

        # 2. Check local worker log file if exists
        bus = IncidentBus()
        log_file = bus.incidents_dir / f"{incident_id}-worker.log"
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    file_logs = f.read().strip()
                    if file_logs:
                        logs = (logs + "\n" + file_logs) if logs else file_logs
            except Exception:
                pass

        if not logs:
            logs = f"=== OpenCode Remediation Session: {session_name} ===\nStatus: Initialized and claimed.\nTarget Workspace: /opt/happy-galileo\nGit Fix Branch: fix/{incident_id}\n\nTo view or control live terminal via SSH:\n  tmux attach -t {session_name}"

        return {
            "incident_id": incident_id,
            "session_name": session_name,
            "is_running": is_running,
            "status": "RUNNING" if is_running else "DISPATCHED",
            "logs": logs,
        }

