#!/usr/bin/env bash
# ==============================================================================
# CENTRAL HUB Setup Script
# Purpose: Sets up the MAIN server that runs the Fleet Dashboard, receives
#          telemetry from all nodes, and aggregates incidents fleet-wide.
#
# What it installs:
#   - Docker & Docker Compose
#   - Node.js & Playwright (for visual testing)
#   - OpenCode CLI (autonomous code remediation agent)
#   - devctl CLI (service management)
#   - Caddy reverse proxy (wildcard TLS)
#   - AI-Ops monitoring daemon
#   - Fleet Status Dashboard (the central web UI)
#   - Firewall (UFW) & Fail2ban
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Unlimited-demi/happy-galileo/master/scripts/setup-hub.sh | sudo bash
#   # or with custom domain:
#   sudo bash scripts/setup-hub.sh --domain dev-server.datakrib.com
# ==============================================================================

set -e

BASE_DOMAIN="${BASE_DOMAIN:-dev-server.datakrib.com}"
NODE_NAME="${NODE_NAME:-}"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --domain) BASE_DOMAIN="$2"; shift ;;
    --name) NODE_NAME="$2"; shift ;;
    *) echo "Unknown parameter: $1"; exit 1 ;;
  esac
  shift
done

# Default node name for hub
if [ -z "$NODE_NAME" ]; then
  NODE_NAME="hub-$(hostname -s)"
fi

echo "========================================================"
echo "🌐 Setting up CENTRAL FLEET HUB"
echo "   Domain Scope:     *.${BASE_DOMAIN}"
echo "   Node Name:        ${NODE_NAME}"
echo "   Role:             CENTRAL HUB (Dashboard + Telemetry Receiver)"
echo "========================================================"

if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root: sudo bash scripts/setup-hub.sh [--domain <your-domain>]"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEBIAN_FRONTEND=noninteractive
export BASE_DOMAIN

echo "[1/9] Updating package lists..."
apt-get update -y
apt-get install -y \
  apt-transport-https \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  git \
  tmux \
  ufw \
  fail2ban \
  python3 \
  python3-pip \
  python3-venv \
  jq

echo "[2/9] Installing Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh
  rm get-docker.sh
  systemctl enable docker
  systemctl start docker
fi
apt-get install -y docker-compose-plugin 2>/dev/null || true

echo "[3/9] Installing Node.js & Playwright..."
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi
cd "${PROJECT_DIR}"
if [ -f "package.json" ]; then
  npm install 2>/dev/null || true
  npx playwright install-deps chromium 2>/dev/null || true
  npx playwright install chromium 2>/dev/null || true
fi

echo "[4/9] Installing OpenCode CLI..."
if ! command -v opencode &> /dev/null; then
  npm install -g opencode-ai 2>/dev/null || npm install -g @opencode/cli 2>/dev/null || echo "[!] OpenCode not found in npm. Install manually."
fi

echo "[5/9] Creating internal Docker network 'dev-net'..."
docker network inspect dev-net &>/dev/null || docker network create dev-net

echo "[6/9] Hardening Firewall (UFW) & Fail2ban..."
if [ -f "${PROJECT_DIR}/infra/security/ufw_setup.sh" ]; then
  bash "${PROJECT_DIR}/infra/security/ufw_setup.sh"
fi
if [ -d "/etc/fail2ban" ] && [ -f "${PROJECT_DIR}/infra/security/fail2ban/jail.local" ]; then
  cp "${PROJECT_DIR}/infra/security/fail2ban/jail.local" /etc/fail2ban/jail.local
  mkdir -p /etc/fail2ban/filter.d
  cp "${PROJECT_DIR}/infra/security/fail2ban/filter.d/caddy-badbots.conf" /etc/fail2ban/filter.d/caddy-badbots.conf 2>/dev/null || true
  systemctl restart fail2ban || true
fi

echo "[7/9] Installing 'devctl' CLI globally..."
VENV_DIR="/opt/devctl-venv"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
if [ -f "${PROJECT_DIR}/requirements.txt" ]; then
  "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
fi

# Symlink project to /opt/happy-galileo
if [ "${PROJECT_DIR}" != "/opt/happy-galileo" ]; then
  mkdir -p /opt
  ln -sfn "${PROJECT_DIR}" /opt/happy-galileo
fi

cat << EOF > /usr/local/bin/devctl
#!/usr/bin/env bash
export PYTHONPATH="/opt/happy-galileo:\${PYTHONPATH}"
export BASE_DOMAIN="\${BASE_DOMAIN:-${BASE_DOMAIN}}"
export NODE_NAME="\${NODE_NAME:-${NODE_NAME}}"
export CADDY_ADMIN_API="\${CADDY_ADMIN_API:-http://127.0.0.1:2019}"
export DEVCTL_DOCKER_NETWORK="\${DEVCTL_DOCKER_NETWORK:-dev-net}"
exec /opt/devctl-venv/bin/python3 /opt/happy-galileo/devctl/cli.py "\$@"
EOF
chmod +x /usr/local/bin/devctl
chmod +x "${PROJECT_DIR}/devctl/cli.py"

echo "[8/9] Resolving existing reverse proxy conflicts..."
if [ -f "${PROJECT_DIR}/infra/security/proxy_resolver.sh" ]; then
  bash "${PROJECT_DIR}/infra/security/proxy_resolver.sh" "${BASE_DOMAIN}"
fi

echo "[9/9] Starting Central Hub Stack (Caddy + Dashboard + AI-Ops)..."
# Write hub .env
cat << EOF > "${PROJECT_DIR}/infra/.env"
BASE_DOMAIN=${BASE_DOMAIN}
NODE_NAME=${NODE_NAME}
CENTRAL_HUB_URL=
FLEET_KEY=
EOF

cd "${PROJECT_DIR}/infra"
docker compose -f docker-compose.infra.yml --env-file .env up -d

echo ""
echo "========================================================"
echo "🎉 Central Fleet Hub Setup Complete!"
echo "========================================================"
echo "• Role:              CENTRAL HUB"
echo "• Public Wildcard:   *.${BASE_DOMAIN}"
echo "• Fleet Dashboard:   https://status.${BASE_DOMAIN}"
echo "• Internal Network:  dev-net (Zero public ports on apps)"
echo "• devctl CLI:        /usr/local/bin/devctl"
echo "• OpenCode:          $(command -v opencode 2>/dev/null || echo 'Not installed')"
echo "========================================================"
echo ""
echo "📡 Remote nodes connect to this hub using:"
echo "   curl -sSL https://raw.githubusercontent.com/Unlimited-demi/happy-galileo/master/scripts/setup-node.sh | \\"
echo "     sudo bash -s -- \\"
echo "       --node-name \"my-server\" \\"
echo "       --domain \"my-server.${BASE_DOMAIN}\" \\"
echo "       --hub-url \"https://status.${BASE_DOMAIN}/api/telemetry/ingest\""
echo ""

# Run doctor
devctl doctor
