#!/usr/bin/env bash
# ==============================================================================
# ARA Autonomous Fleet Node Setup (Forwarder & Upgrade Delegator)
#
# NOTE: The heavyweight setup-node.sh script has been replaced with the
# production lightweight ARA agent installer (scripts/install-agent.sh).
# This ensures zero port conflicts, non-destructive operation, and direct
# container log streaming.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="${SCRIPT_DIR}/install-agent.sh"

echo "========================================================"
echo "🛰️  ARA Fleet Node Setup"
echo "   Delegating to production lightweight agent installer..."
echo "========================================================"

if [ -f "${INSTALLER}" ]; then
  exec bash "${INSTALLER}" "$@"
else
  # Fetch installer from Central Hub or repository
  HUB_ARG=""
  for arg in "$@"; do
    if [[ "${prev}" == "--hub" || "${prev}" == "--hub-url" ]]; then
      HUB_ARG="${arg}"
    fi
    prev="${arg}"
  done
  HUB_URL="${HUB_ARG:-https://ara.suburbancloud.ng}"
  echo "[*] Fetching install-agent.sh from ${HUB_URL}..."
  exec curl -fsSL "${HUB_URL%/}/install-agent.sh" | bash -s -- "$@"
fi
