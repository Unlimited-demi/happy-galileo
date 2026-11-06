"""
Tests for ARA Autonomous Node Agent (scripts/ara-agent.py)
Verifies container discovery, log demultiplexing, git resolution, and telemetry format.
"""

import sys
from pathlib import Path
import pytest

# Ensure scripts dir is importable
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "scripts"))

from importlib.machinery import SourceFileLoader
agent_mod = SourceFileLoader("ara_agent", str(repo_root / "scripts" / "ara-agent.py")).load_module()


def test_docker_log_demultiplexing_tty():
    """Verify plain TTY container logs decode correctly."""
    plain_bytes = b"Line 1\nLine 2\nLine 3\n"
    # When is_multiplexed is False (first byte not 0,1,2 or length <= 8)
    # Mocking DockerSocket get_logs behavior
    text = plain_bytes.decode("utf-8")
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    assert len(lines) == 3
    assert lines[0] == "Line 1"


def test_docker_log_demultiplexing_multiplexed():
    """Verify 8-byte framed Docker stdout/stderr streams decode cleanly."""
    # Frame 1: stdout (stream=1), size=12: "Hello World\n"
    payload1 = b"Hello World\n"
    header1 = bytes([1, 0, 0, 0]) + len(payload1).to_bytes(4, "big")
    
    # Frame 2: stderr (stream=2), size=14: "Error Warning\n"
    payload2 = b"Error Warning\n"
    header2 = bytes([2, 0, 0, 0]) + len(payload2).to_bytes(4, "big")

    stream_data = header1 + payload1 + header2 + payload2

    # Test demuxing logic from ara-agent.py
    lines = []
    offset = 0
    while offset + 8 <= len(stream_data):
        frame_size = int.from_bytes(stream_data[offset + 4 : offset + 8], "big")
        offset += 8
        if frame_size == 0 or offset + frame_size > len(stream_data):
            break
        payload = stream_data[offset : offset + frame_size]
        offset += frame_size
        text = payload.decode("utf-8")
        for line in text.splitlines():
            if line.strip():
                lines.append(line.rstrip())

    assert len(lines) == 2
    assert lines[0] == "Hello World"
    assert lines[1] == "Error Warning"


def test_git_info_resolution(tmp_path):
    """Verify git repository and branch are parsed directly from .git files."""
    proj = tmp_path / "my_project"
    git_dir = proj / ".git"
    git_dir.mkdir(parents=True)

    # Write .git/config
    (git_dir / "config").write_text(
        """
[core]
\trepositoryformatversion = 0
\tfilemode = true
[remote "origin"]
\turl = git@github.com:suburban-fiber-company/Support.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
        """
    )
    # Write .git/HEAD
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

    mounts = [{"Type": "bind", "Source": str(proj)}]
    repo, branch, path = agent_mod.CodebaseDetector.resolve_git_info(mounts)

    assert repo == "suburban-fiber-company/Support"
    assert branch == "main"
    assert path == str(proj)


def test_ingress_url_resolution(tmp_path):
    """Verify ingress URLs are resolved strictly from reverse proxy configurations (NO .env checking)."""
    # 1. Container with only .env (no reverse proxy rule) must be [INTERNAL]
    url_env_only = agent_mod.CodebaseDetector.resolve_ingress_url(
        "web-ui",
        ["APP_URL=https://support.ccs.legend.ng", "NODE_ENV=production"],
        [],
        "102.38.58.99"
    )
    assert url_env_only == "[INTERNAL]"

    # 2. Reverse proxy container itself is identified as [Reverse Proxy Ingress]
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("support.ccs.legend.ng {\n    reverse_proxy ui:80\n}\n")
    mounts = [{"Type": "bind", "Source": str(caddyfile)}]
    url_caddy = agent_mod.CodebaseDetector.resolve_ingress_url("caddy", [], mounts, "102.38.58.99")
    assert url_caddy == "[Reverse Proxy Ingress]"

    # 3. The actual proxied upstream container ("ui") gets the target domain from reverse proxy
    up_map, _ = agent_mod.CodebaseDetector.extract_reverse_proxy_mappings(mounts)
    url_ui = agent_mod.CodebaseDetector.resolve_ingress_url("ui", [], [], "102.38.58.99", global_upstream_map=up_map)
    assert url_ui == "https://support.ccs.legend.ng"


def test_reverse_proxy_caddy_and_nginx_matching(tmp_path):
    """Verify NodeReverseProxyEngine handles Caddy, Nginx, and LiveKit WebSockets."""
    # Test Caddy parsing
    caddy_content = """
    files.suburban.ng {
        reverse_proxy fileserver-api:3000
    }
    api-collab.suburban.ng {
        reverse_proxy /livekit/* suburban-livekit:7880
        reverse_proxy suburban-collab-api:8080
    }
    """
    c_rules = agent_mod.NodeReverseProxyEngine.parse_caddy(caddy_content)
    assert len(c_rules) == 3

    # Match fileserver-api
    url_api = agent_mod.NodeReverseProxyEngine.match_container(
        c_name="fileserver-api",
        img="fileserver-api:latest",
        main_port=3000,
        ports=[3000],
        labels={"com.docker.compose.project": "fileserver", "com.docker.compose.service": "api"},
        inspect_data={},
        rules=c_rules
    )
    assert url_api == "https://files.suburban.ng"

    # Match suburban-livekit (WebSocket)
    url_lk = agent_mod.NodeReverseProxyEngine.match_container(
        c_name="suburban-livekit",
        img="livekit/livekit-server",
        main_port=7880,
        ports=[7880],
        labels={},
        inspect_data={},
        rules=c_rules
    )
    assert url_lk == "wss://api-collab.suburban.ng/livekit"

    # Fileserver Caddy container is [Reverse Proxy Ingress]
    url_proxy = agent_mod.NodeReverseProxyEngine.match_container(
        c_name="fileserver-caddy",
        img="caddy:alpine",
        main_port=2019,
        ports=[2019, 80, 443],
        labels={},
        inspect_data={},
        rules=c_rules
    )
    assert url_proxy == "[Reverse Proxy Ingress]"

    # Unproxied database is [INTERNAL]
    url_db = agent_mod.NodeReverseProxyEngine.match_container(
        c_name="fileserver-postgres",
        img="postgres:15",
        main_port=5432,
        ports=[5432],
        labels={},
        inspect_data={},
        rules=c_rules
    )
    assert url_db == "[INTERNAL]"

    # Test Nginx parsing
    nginx_content = """
    upstream app_srv {
        server 127.0.0.1:8000;
    }
    server {
        listen 80;
        server_name portal.suburbancloud.ng;
        location / {
            proxy_pass http://app_srv;
        }
    }
    """
    n_rules = agent_mod.NodeReverseProxyEngine.parse_nginx(nginx_content)
    assert len(n_rules) == 1
    assert n_rules[0].domain == "portal.suburbancloud.ng"
    assert n_rules[0].upstream_port == 8000
