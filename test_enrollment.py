"""Test Autonomous Enrollment and Codebase Resolution."""
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# Setup test environment
test_root = Path(tempfile.mkdtemp(prefix="enrollment_test_"))
os.environ["DEVCTL_STATE_DIR"] = str(test_root / "state")
(test_root / "state").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, r"C:\Users\Admin\Documents\antigravity\happy-galileo")

failures = []
def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failures.append(name)

# 1. Simulate an existing project on disk
app_dir = test_root / "my-web-app"
app_dir.mkdir()
(app_dir / "docker-compose.yml").write_text("services: { web: { image: nginx } }")
git_dir = app_dir / ".git"
git_dir.mkdir()
(git_dir / "config").write_text('[remote "origin"]\n    url = https://github.com/user/my-web-app.git\n\n[head]\n    ref = refs/heads/feature-1')
(git_dir / "HEAD").write_text("ref: refs/heads/feature-1")

# 2. Mock all Docker dependencies
# discover_and_index_containers uses:
#   - subprocess.run(["docker", "ps", ...]) for container names
#   - DockerManager (from devctl.core.docker_mgr) for inspect_container, detect_ports, connect_to_network
#   - AIContainerInference (from devctl.core.ai_discovery) for inspect_and_infer
#   - CodebaseResolver (from ai_ops.codebase_resolver) which uses DockerSocket internally
#   - DomainRegistry.detect_existing_domains which also calls subprocess and DockerManager

container_inspect_info = {
    "Config": {
        "Image": "nginx:latest",
        "Labels": {
            "com.docker.compose.project.working_dir": str(app_dir),
            "com.docker.compose.project.config_files": "docker-compose.yml",
            "com.docker.compose.service": "web",
        },
        "ExposedPorts": {"80/tcp": {}},
        "Env": [],
    },
    "Mounts": [],
    "NetworkSettings": {"Ports": {}, "Networks": {"bridge": {}}},
    "State": {"Running": True, "Status": "running"},
}

def mock_subprocess_run(cmd, **kwargs):
    """Mock subprocess.run for docker ps and other shell commands."""
    if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "docker":
        if cmd[1] == "ps":
            return MagicMock(returncode=0, stdout="my-web-app\n")
        elif cmd[1] == "network":
            return MagicMock(returncode=0, stdout="")
    # Default: return success with empty output
    return MagicMock(returncode=0, stdout="", stderr="")

# Mock DockerSocket (used by CodebaseResolver internally)
mock_docker_socket_instance = MagicMock()
mock_docker_socket_instance.inspect_container.return_value = container_inspect_info

# Mock DockerManager (used by discover_and_index_containers)
mock_docker_mgr_instance = MagicMock()
mock_docker_mgr_instance.inspect_container.return_value = container_inspect_info
mock_docker_mgr_instance.detect_ports.return_value = [80]
mock_docker_mgr_instance.connect_to_network.return_value = True

# Mock AIContainerInference
mock_ai_inference_instance = MagicMock()
mock_ai_inference_instance.inspect_and_infer.return_value = {
    "archetype": "web",
    "recommended_port": 80,
    "role_label": "Web Application",
}

with patch("subprocess.run", side_effect=mock_subprocess_run), \
     patch("devctl.core.docker_mgr.DockerManager", return_value=mock_docker_mgr_instance), \
     patch("devctl.core.ai_discovery.AIContainerInference", return_value=mock_ai_inference_instance), \
     patch("ai_ops.codebase_resolver.DockerSocket", return_value=mock_docker_socket_instance):

    # 3. Run Discovery
    from devctl.core.domains import DomainRegistry
    registry = DomainRegistry(state_file=test_root / "state" / "state.json")
    discovered = registry.discover_and_index_containers()

    # 4. Verify
    svc = registry.get_service("my-web-app")
    check("Service discovered", svc is not None, f"services: {list(registry._load_state().get('services', {}).keys())}")
    if svc:
        check("Workspace resolved", svc.get("workspace_dir") == str(app_dir),
              f"got: {svc.get('workspace_dir')}")
        check("Compose file resolved", "docker-compose.yml" in (svc.get("compose_file") or ""),
              f"got: {svc.get('compose_file')}")

        codebase = (svc.get("metadata") or {}).get("codebase") or {}
        check("Git URL resolved", codebase.get("git_url") == "https://github.com/user/my-web-app.git",
              f"got: {codebase.get('git_url')}")
        check("Git branch resolved", codebase.get("git_branch") == "feature-1",
              f"got: {codebase.get('git_branch')}")
        check("Container type is web", svc.get("container_type") == "web",
              f"got: {svc.get('container_type')}")

# 5. Test CodebaseResolver directly (isolated test)
print("\n--- Direct CodebaseResolver Test ---")
with patch("ai_ops.codebase_resolver.DockerSocket", return_value=mock_docker_socket_instance):
    from ai_ops.codebase_resolver import CodebaseResolver
    resolver = CodebaseResolver()
    result = resolver.resolve("my-web-app")
    check("Resolver: workspace_dir", result["workspace_dir"] == str(app_dir),
          f"got: {result['workspace_dir']}")
    check("Resolver: compose_file", result["compose_file"] is not None and "docker-compose.yml" in result["compose_file"],
          f"got: {result['compose_file']}")
    check("Resolver: git_url", result["git_url"] == "https://github.com/user/my-web-app.git",
          f"got: {result['git_url']}")
    check("Resolver: git_branch", result["git_branch"] == "feature-1",
          f"got: {result['git_branch']}")

# Cleanup
shutil.rmtree(test_root, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL ENROLLMENT TESTS PASSED")
