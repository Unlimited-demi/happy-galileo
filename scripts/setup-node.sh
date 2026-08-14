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
INSTALL_DIR="/opt/happy-galileo"
REPO_URL="https://github.com/Unlimited-demi/happy-galileo.git"

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

export DEBIAN_FRONTEND=noninteractive
export BASE_DOMAIN

# 1. Ensure git & curl are available
if ! command -v git &>/dev/null || ! command -v curl &>/dev/null; then
  echo "[1/4] Installing prerequisite git & curl..."
  apt-get update -y
  apt-get install -y git curl
fi

# 2. Clone or update repository into /opt/happy-galileo
echo "[2/4] Fetching workstation codebase..."
if [ ! -d "${INSTALL_DIR}" ]; then
  mkdir -p /opt
  git clone "${REPO_URL}" "${INSTALL_DIR}"
else
  cd "${INSTALL_DIR}"
  git fetch origin master
  git reset --hard origin/master || true
fi

# 3. Run proxy resolver to auto-detect existing Nginx/Apache
if [ -f "${INSTALL_DIR}/infra/security/proxy_resolver.sh" ]; then
  bash "${INSTALL_DIR}/infra/security/proxy_resolver.sh" "${BASE_DOMAIN}"
fi

# 4. Run full workstation setup
echo "[3/4] Running core infrastructure & security setup..."
bash "${INSTALL_DIR}/scripts/setup-server.sh" --domain "${BASE_DOMAIN}"

# 5. Configure Telemetry streamer if Central Hub URL provided
if [ -n "${CENTRAL_HUB_URL}" ]; then
  echo "[4/4] Configuring Fleet Telemetry Streamer..."
  cat << EOF > "${INSTALL_DIR}/.env.node"
NODE_NAME=${NODE_NAME}
BASE_DOMAIN=${BASE_DOMAIN}
CENTRAL_HUB_URL=${CENTRAL_HUB_URL}
FLEET_KEY=${FLEET_KEY}
EOF
fi

# 6. Auto-discover any existing Docker containers on this machine
if command -v devctl &>/dev/null; then
  devctl discover 2>/dev/null || true
fi

echo ""
echo "========================================================"
echo "🎉 Node Agent Setup Complete for ${NODE_NAME}!"
echo "   Public Wildcard: *.${BASE_DOMAIN}"
echo "   Dashboard:       https://status.${BASE_DOMAIN}"
echo "   devctl CLI:      /usr/local/bin/devctl"
echo "========================================================"
