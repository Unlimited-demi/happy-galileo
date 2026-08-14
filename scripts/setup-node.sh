#!/usr/bin/env bash
# ==============================================================================
# Node Agent Turnkey Setup Script (for multi-server fleet)
# Installs: Docker, Caddy, Fail2ban, UFW, devctl, AI-Ops Sentry, and Fleet Telemetry
# ==============================================================================

set -e

NODE_NAME="${NODE_NAME:-$(hostname)}"
BASE_DOMAIN="${BASE_DOMAIN:-dev-server.datakrib.com}"
CENTRAL_HUB_URL="${CENTRAL_HUB_URL:-}"
FLEET_KEY="${FLEET_KEY:-default-fleet-key}"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --node-name) NODE_NAME="$2"; shift ;;
    --domain) BASE_DOMAIN="$2"; shift ;;
    --hub-url) CENTRAL_HUB_URL="$2"; shift ;;
    --fleet-key) FLEET_KEY="$2"; shift ;;
    *) echo "Unknown parameter: $1"; exit 1 ;;
  esac
  shift
done

echo "========================================================"
echo "🚀 Installing AI-Ops Node Agent on: ${NODE_NAME}"
echo "   Domain Scope:       *.${BASE_DOMAIN}"
echo "   Central Hub URL:    ${CENTRAL_HUB_URL:-None (Standalone)}"
echo "========================================================"

if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root: sudo bash scripts/setup-node.sh"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEBIAN_FRONTEND=noninteractive
export BASE_DOMAIN

# Run base server setup
bash "${PROJECT_DIR}/scripts/setup-server.sh" --domain "${BASE_DOMAIN}"

# Configure Telemetry in infra stack if HUB URL provided
if [ -n "${CENTRAL_HUB_URL}" ]; then
  echo "[*] Configuring Fleet Telemetry Streamer..."
  cat << EOF > "${PROJECT_DIR}/.env.node"
NODE_NAME=${NODE_NAME}
BASE_DOMAIN=${BASE_DOMAIN}
CENTRAL_HUB_URL=${CENTRAL_HUB_URL}
FLEET_KEY=${FLEET_KEY}
EOF
fi

echo ""
echo "========================================================"
echo "🎉 Node Agent Setup Complete for ${NODE_NAME}!"
echo "   Public Wildcard: *.${BASE_DOMAIN}"
echo "   devctl CLI:      /usr/local/bin/devctl"
echo "========================================================"
