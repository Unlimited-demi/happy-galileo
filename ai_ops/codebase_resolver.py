"""
Codebase Resolver for AI-Ops.
Automatically maps running Docker containers to their source code,
git repositories, and project workspaces on the host filesystem.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from ai_ops.docker_socket import DockerSocket

class CodebaseResolver:
    """Resolves the physical source code location and git metadata for a container."""

    def __init__(self):
        self.docker = DockerSocket()

    def resolve(self, container_name: str) -> Dict[str, Any]:
        """
        Attempt to locate the source code and git repository for a given container.
        Returns a dict with workspace_dir, compose_file, and git_url.
        """
        result = {
            "workspace_dir": None,
            "compose_file": None,
            "git_url": None,
            "git_branch": "master",
        }

        try:
            info = self.docker.inspect_container(container_name)
            if not info:
                return result

            # 1. Try Docker Compose labels (most reliable)
            labels = info.get("Config", {}).get("Labels", {}) or {}
            workspace_dir = labels.get("com.docker.compose.project.working_dir")
            compose_file = labels.get("com.docker.compose.project.config_files")

            if not workspace_dir:
                # 2. Try bind mounts (fallback)
                workspace_dir = self._find_workspace_from_mounts(info.get("Mounts", []) or [])

            if workspace_dir:
                result["workspace_dir"] = workspace_dir
                # If compose_file wasn't in labels, try to find it in the workspace
                if not compose_file:
                    compose_file = self._find_compose_file(workspace_dir)
                result["compose_file"] = compose_file

                # 3. Extract Git Metadata
                git_info = self._extract_git_metadata(workspace_dir)
                result["git_url"] = git_info.get("url")
                result["git_branch"] = git_info.get("branch", "master")

        except Exception as e:
            print(f"[CodebaseResolver] Error resolving {container_name}: {e}")

        return result

    def _find_workspace_from_mounts(self, mounts: list) -> Optional[str]:
        """Heuristically find the project root from container bind mounts."""
        for m in mounts:
            if m.get("Type") == "bind":
                src = m.get("Source", "")
                if not src or not os.path.isdir(src):
                    continue

                # Check if this mount is already a project root (has compose/git)
                path = Path(src)
                if any((path / f).exists() for f in ["docker-compose.yml", "docker-compose.yaml", ".git"]):
                    return src

                # Walk up 3 levels to find the project root
                for p in list(path.parents)[:3]:
                    if any((p / f).exists() for f in ["docker-compose.yml", "docker-compose.yaml", ".git"]):
                        return str(p)
        return None

    def _find_compose_file(self, workspace_dir: str) -> Optional[str]:
        """Find the compose file within a workspace."""
        wp = Path(workspace_dir)
        for f in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
            if (wp / f).exists():
                return str(wp / f)
        return None

    def _extract_git_metadata(self, workspace_dir: str) -> Dict[str, Any]:
        """Extract remote URL and current branch from the .git directory."""
        git_dir = Path(workspace_dir) / ".git"
        if not git_dir.exists():
            return {}

        metadata = {}
        try:
            # Extract remote URL from .git/config
            config_path = git_dir / "config"
            if config_path.exists():
                content = config_path.read_text(encoding="utf-8", errors="ignore")
                # Find [remote "origin"] then the url = ... line
                match = re.search(r'\[remote\s+"origin"\]\s*[^\]]*\n\s*url\s*=\s*([^\s]+)', content, re.MULTILINE)
                if match:
                    metadata["url"] = match.group(1).strip()

            # Extract current branch from .git/HEAD
            head_path = git_dir / "HEAD"
            if head_path.exists():
                head = head_path.read_text(encoding="utf-8", errors="ignore").strip()
                if head.startswith("ref: refs/heads/"):
                    metadata["branch"] = head.split("/")[-1]
                else:
                    # Detached HEAD (hash)
                    metadata["branch"] = head[:7]
        except Exception:
            pass

        return metadata
