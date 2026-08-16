"""
AI-Driven Container Introspector and Inference Engine.
Analyzes container runtime metadata, process signatures, exposed ports,
environment variable keys, and startup log banners to intelligently infer
container archetype, exposure safety, upstream dependencies, and operational recommendations.
"""

import re
import json
from typing import Dict, List, Any, Optional
from ai_ops.docker_socket import DockerSocket


class ContainerArchetype:
    WEB_FRONTEND = "web_frontend"
    API_SERVICE = "api_service"
    RELATIONAL_DB = "database_relational"
    NOSQL_DB = "database_nosql"
    CACHE_STORE = "cache_store"
    MESSAGE_QUEUE = "message_queue"
    MAIL_DAEMON = "mail_subsystem"
    BACKGROUND_WORKER = "background_worker"
    INGRESS_PROXY = "ingress_proxy"
    STORAGE_SERVICE = "storage_service"
    SYSTEM_INTERNAL = "system_internal"


class AIContainerInference:
    """Intelligently classifies and infers architecture roles for running Docker containers."""

    def __init__(self, docker: Optional[DockerSocket] = None):
        self.docker = docker or DockerSocket()

    def inspect_and_infer(self, container_name: str) -> Dict[str, Any]:
        """
        Deeply inspect a container and generate an architectural inference profile.
        """
        info = self.docker.inspect_container(container_name)
        if not info:
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.SYSTEM_INTERNAL,
                "role_label": "Unknown Container",
                "is_publicly_exposable": False,
                "recommended_port": None,
                "dependencies": [],
                "confidence": 0.0,
                "rationale": "Container not found or inaccessible.",
            }

        config = info.get("Config", {})
        image = config.get("Image", "")
        # Normalize Cmd and Entrypoint — may be string, list, or None
        raw_cmd = config.get("Cmd") or []
        raw_entry = config.get("Entrypoint") or []
        if isinstance(raw_cmd, str):
            raw_cmd = [raw_cmd]
        if isinstance(raw_entry, str):
            raw_entry = [raw_entry]
        cmd = " ".join(raw_cmd)
        entrypoint = " ".join(raw_entry)
        labels = config.get("Labels") or {}
        env_vars = config.get("Env") or []
        env_keys = [e.split("=")[0] for e in env_vars if "=" in e]

        # Extract exposed ports & port bindings
        network_settings = info.get("NetworkSettings", {})
        ports_dict = network_settings.get("Ports") or {}
        exposed_ports = []
        for port_proto in ports_dict.keys():
            try:
                p = int(port_proto.split("/")[0])
                exposed_ports.append(p)
            except Exception:
                pass

        # Fetch recent logs for startup banners
        logs_sample = self.docker.get_logs(container_name, tail=20)

        # Inspect codebase, workspace location, and git repository context
        codebase_info = self._inspect_codebase(container_name, info)

        # Run inference rules
        profile = self._evaluate_profile(
            container_name=container_name,
            image=image,
            cmd=cmd,
            entrypoint=entrypoint,
            labels=labels,
            env_keys=env_keys,
            exposed_ports=exposed_ports,
            logs_sample=logs_sample,
        )
        profile["codebase"] = codebase_info
        return profile

    def _inspect_codebase(self, container_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inspect host codebase, git repo, compose working directory, and bind mounts for a container.
        This provides OpenCode with the exact directory path to checkout fix branches and rebuild.
        """
        import os
        import subprocess
        from pathlib import Path

        labels = info.get("Config", {}).get("Labels", {}) or {}
        mounts = info.get("Mounts", []) or []

        # 1. Check Docker Compose project working directory
        compose_work_dir = labels.get("com.docker.compose.project.working_dir")
        compose_file = labels.get("com.docker.compose.project.config_files")
        compose_service = labels.get("com.docker.compose.service", container_name)
        compose_project = labels.get("com.docker.compose.project", "")

        # 2. Check bind mounts to locate host source code directories
        bind_mounts = []
        candidate_dirs = []
        if compose_work_dir:
            candidate_dirs.append(compose_work_dir)

        for m in mounts:
            if m.get("Type") == "bind":
                src = m.get("Source", "")
                dst = m.get("Destination", "")
                if src and os.path.exists(src):
                    bind_mounts.append({"host_path": src, "container_path": dst})
                    candidate_dirs.append(src)

        # 3. Determine the primary workspace directory
        workspace_dir = None
        for cd in candidate_dirs:
            p = Path(cd)
            if p.is_dir():
                workspace_dir = str(p.resolve())
                break

        # Fallback search if not found in compose labels
        if not workspace_dir and bind_mounts:
            workspace_dir = bind_mounts[0]["host_path"]

        # 4. Check for Git repository & active branch
        is_git_repo = False
        git_root = None
        git_branch = None
        git_remote = None
        git_commit = None

        if workspace_dir:
            try:
                # Walk up to find .git directory
                curr = Path(workspace_dir)
                for parent in [curr] + list(curr.parents):
                    if (parent / ".git").exists():
                        is_git_repo = True
                        git_root = str(parent)
                        break

                if is_git_repo and git_root:
                    # Query git branch
                    try:
                        res = subprocess.run(
                            ["git", "-C", git_root, "rev-parse", "--abbrev-ref", "HEAD"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=2,
                            check=False,
                        )
                        if res.returncode == 0:
                            git_branch = res.stdout.strip()
                    except Exception:
                        pass

                    # Query git remote URL
                    try:
                        res = subprocess.run(
                            ["git", "-C", git_root, "remote", "get-url", "origin"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=2,
                            check=False,
                        )
                        if res.returncode == 0:
                            git_remote = res.stdout.strip()
                    except Exception:
                        pass

                    # Query latest commit
                    try:
                        res = subprocess.run(
                            ["git", "-C", git_root, "log", "-1", "--oneline"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=2,
                            check=False,
                        )
                        if res.returncode == 0:
                            git_commit = res.stdout.strip()
                    except Exception:
                        pass
            except Exception:
                pass

        # 5. Detect project type / stack markers in workspace
        project_type = "Docker Container"
        if workspace_dir and os.path.exists(workspace_dir):
            try:
                wp = Path(workspace_dir)
                if (wp / "package.json").exists():
                    project_type = "Node.js / JavaScript"
                elif (wp / "tsconfig.json").exists():
                    project_type = "TypeScript"
                elif (wp / "requirements.txt").exists() or (wp / "pyproject.toml").exists() or (wp / "Pipfile").exists():
                    project_type = "Python"
                elif (wp / "go.mod").exists():
                    project_type = "Go (Golang)"
                elif (wp / "Cargo.toml").exists():
                    project_type = "Rust"
                elif (wp / "composer.json").exists():
                    project_type = "PHP"
                elif (wp / "Gemfile").exists():
                    project_type = "Ruby"
                elif (wp / "pom.xml").exists() or (wp / "build.gradle").exists():
                    project_type = "Java / JVM"
            except Exception:
                pass

        return {
            "workspace_dir": workspace_dir,
            "compose_file": compose_file,
            "compose_service": compose_service,
            "compose_project": compose_project,
            "is_git_repo": is_git_repo,
            "git_root": git_root,
            "git_branch": git_branch or "master",
            "git_remote": git_remote,
            "git_commit": git_commit,
            "bind_mounts": bind_mounts,
            "project_type": project_type,
        }

    def _evaluate_profile(
        self,
        container_name: str,
        image: str,
        cmd: str,
        entrypoint: str,
        labels: Dict[str, str],
        env_keys: List[str],
        exposed_ports: List[int],
        logs_sample: str,
    ) -> Dict[str, Any]:
        combined_text = f"{container_name} {image} {cmd} {entrypoint} {' '.join(labels.values())}".lower()
        logs_lower = logs_sample.lower()

        dependencies = []
        # Check env keys for dependency hints
        for k in env_keys:
            k_upper = k.upper()
            if any(term in k_upper for term in ["POSTGRES", "PG_HOST", "DATABASE_URL", "MYSQL", "MARIADB", "DB_HOST"]):
                if "database" not in dependencies:
                    dependencies.append("database")
            if any(term in k_upper for term in ["REDIS", "CACHE_HOST", "MEMCACHED"]):
                if "cache" not in dependencies:
                    dependencies.append("cache")
            if any(term in k_upper for term in ["S3", "MINIO", "AWS_BUCKET"]):
                if "object_storage" not in dependencies:
                    dependencies.append("object_storage")
            if any(term in k_upper for term in ["RABBITMQ", "KAFKA", "NATS", "AMQP"]):
                if "message_broker" not in dependencies:
                    dependencies.append("message_broker")

        # 1. Relational Databases
        if any(term in combined_text for term in ["postgres", "mysql", "mariadb", "cockroach", "timescale"]):
            port = 5432 if "postgres" in combined_text else 3306
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.RELATIONAL_DB,
                "role_label": "Relational Database",
                "is_publicly_exposable": False,
                "recommended_port": port,
                "dependencies": [],
                "confidence": 0.98,
                "rationale": f"Identified database engine ({image}) managing persistent state. Public exposure disabled for security.",
            }

        # 2. In-memory Cache & Key-Value
        if any(term in combined_text for term in ["redis", "memcached", "valkey", "dragonfly", "keydb"]):
            port = 6379 if "redis" in combined_text else (11211 if "memcached" in combined_text else 6379)
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.CACHE_STORE,
                "role_label": "In-Memory Cache & Session Store",
                "is_publicly_exposable": False,
                "recommended_port": port,
                "dependencies": [],
                "confidence": 0.99,
                "rationale": "High-throughput ephemeral key-value/caching system. Restricted to internal network.",
            }

        # 3. Mailcow / Email Infrastructure Daemons
        if any(term in combined_text for term in ["dovecot", "postfix", "rspamd", "clamd", "olefy", "sogo", "mailcow", "watchdog", "ofelia", "unbound"]):
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.MAIL_DAEMON,
                "role_label": "Mail Infrastructure Daemon",
                "is_publicly_exposable": False,
                "recommended_port": None,
                "dependencies": ["mailcow-internal"],
                "confidence": 0.95,
                "rationale": "Dedicated mail routing, anti-spam, or IMAP/SMTP transport component managed by Mailcow orchestrator.",
            }

        # 4. Ingress / Reverse Proxy
        if any(term in combined_text for term in ["caddy", "traefik", "nginx-proxy", "haproxy"]):
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.INGRESS_PROXY,
                "role_label": "TLS Ingress & Reverse Proxy",
                "is_publicly_exposable": False,
                "recommended_port": 80,
                "dependencies": [],
                "confidence": 0.96,
                "rationale": "Primary entrypoint or reverse proxy gateway handling external network ingress.",
            }

        # 5. Object Storage / MinIO
        if any(term in combined_text for term in ["minio", "s3-mock", "localstack"]):
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.STORAGE_SERVICE,
                "role_label": "Object Storage API (S3)",
                "is_publicly_exposable": True,
                "recommended_port": 9000 if 9000 in exposed_ports else (exposed_ports[0] if exposed_ports else 9000),
                "dependencies": [],
                "confidence": 0.92,
                "rationale": "Object storage blob API service.",
            }

        # 6. Web Frontend (React, Vue, Next.js, Nginx static, Svelte)
        if any(term in combined_text for term in ["frontend", "ui", "client", "next", "vite", "nuxt", "spa"]) or "next.js" in logs_lower or "ready in" in logs_lower:
            web_ports = [p for p in exposed_ports if p in [80, 443, 3000, 5173, 8080, 8000]]
            chosen_port = web_ports[0] if web_ports else (exposed_ports[0] if exposed_ports else 3000)
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.WEB_FRONTEND,
                "role_label": "Web Frontend Application",
                "is_publicly_exposable": True,
                "recommended_port": chosen_port,
                "dependencies": dependencies,
                "confidence": 0.94,
                "rationale": f"User interface application serving web clients on port {chosen_port}.",
            }

        # 7. Backend API / Microservice
        if any(term in combined_text for term in ["api", "backend", "server", "service", "graphql", "rest", "gateway"]) or any(term in logs_lower for term in ["listening on", "started server", "uvicorn", "express", "fastify", "nest"]):
            api_ports = [p for p in exposed_ports if p in [80, 443, 8000, 8080, 5000, 4000, 3000, 9000]]
            chosen_port = api_ports[0] if api_ports else (exposed_ports[0] if exposed_ports else 8000)
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.API_SERVICE,
                "role_label": "Backend Application API",
                "is_publicly_exposable": True,
                "recommended_port": chosen_port,
                "dependencies": dependencies,
                "confidence": 0.91,
                "rationale": f"Backend API service handling business logic and HTTP endpoints on port {chosen_port}.",
            }

        # 8. Background Workers / Queues
        if any(term in combined_text for term in ["worker", "celery", "sidekiq", "queue", "consumer", "job", "cron"]):
            return {
                "container_name": container_name,
                "archetype": ContainerArchetype.BACKGROUND_WORKER,
                "role_label": "Async Background Worker",
                "is_publicly_exposable": False,
                "recommended_port": None,
                "dependencies": dependencies,
                "confidence": 0.88,
                "rationale": "Background asynchronous job consumer. No incoming HTTP traffic required.",
            }

        # Default fallback
        is_exposable = bool(exposed_ports and any(p in [80, 443, 3000, 5000, 8000, 8080] for p in exposed_ports))
        port = exposed_ports[0] if exposed_ports else 80
        return {
            "container_name": container_name,
            "archetype": ContainerArchetype.WEB_FRONTEND if is_exposable else ContainerArchetype.SYSTEM_INTERNAL,
            "role_label": "Web Service" if is_exposable else "Internal Component",
            "is_publicly_exposable": is_exposable,
            "recommended_port": port if is_exposable else None,
            "dependencies": dependencies,
            "confidence": 0.70,
            "rationale": f"Inferred based on exposed port profile ({exposed_ports}).",
        }
