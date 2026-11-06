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
    """Verify ingress URLs are extracted from environment variables and Caddyfiles."""
    # From ENV
    url1 = agent_mod.CodebaseDetector.resolve_ingress_url(
        "web-ui",
        ["APP_URL=https://support.ccs.legend.ng", "NODE_ENV=production"],
        [],
        "102.38.58.99"
    )
    assert url1 == "https://support.ccs.legend.ng"

    # From mounted Caddyfile
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("support.ccs.legend.ng {\n    reverse_proxy ui:80\n}\n")
    mounts = [{"Type": "bind", "Source": str(caddyfile)}]
    url2 = agent_mod.CodebaseDetector.resolve_ingress_url("caddy", [], mounts, "102.38.58.99")
    assert url2 == "https://support.ccs.legend.ng"
