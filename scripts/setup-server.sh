#!/usr/bin/env bash
# ==============================================================================
# Full Turnkey Bootstrap Script for AI Remote Workstation
# Configures: Docker, Caddy, Fail2ban, UFW, Node/Playwright, OpenCode, devctl
# Domain Scope: *.dev-server.datakrib.com
# ==============================================================================

set -e

# Parse optional --domain argument
BASE_DOMAIN="${BASE_DOMAIN:-dev-server.datakrib.com}"
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --domain) BASE_DOMAIN="$2"; shift ;;
    *) echo "Unknown parameter: $1"; exit 1 ;;
  esac
  shift
done

echo "========================================================"
echo "🚀 Bootstrapping AI Remote Development Workstation"
echo "   Domain Scope: *.${BASE_DOMAIN}"
echo "========================================================"

# Check root privileges
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root: sudo bash scripts/setup-server.sh [--domain <your-domain>]"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEBIAN_FRONTEND=noninteractive
export BASE_DOMAIN

echo "[1/8] Updating package lists..."
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

echo "[2/8] Installing Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh
  rm get-docker.sh
  systemctl enable docker
  systemctl start docker
fi
apt-get install -y docker-compose-plugin

echo "[3/8] Installing Node.js & Playwright system dependencies..."
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

# Install Node dependencies and Playwright Chromium browser
cd "${PROJECT_DIR}"
if [ -f "package.json" ]; then
  npm install
  npx playwright install-deps chromium 2>/dev/null || true
  npx playwright install chromium 2>/dev/null || true
fi

echo "[4/8] Installing OpenCode CLI..."
if ! command -v opencode &> /dev/null; then
  echo "Installing OpenCode..."
  npm install -g opencode-ai 2>/dev/null || npm install -g @opencode/cli 2>/dev/null || echo "Note: Install opencode via your preferred package manager."
fi

echo "[5/8] Creating internal Docker network 'dev-net'..."
docker network inspect dev-net &>/dev/null || docker network create dev-net

echo "[6/8] Hardening Firewall (UFW) & Fail2ban..."
bash "${PROJECT_DIR}/infra/security/ufw_setup.sh"

if [ -d "/etc/fail2ban" ]; then
  cp "${PROJECT_DIR}/infra/security/fail2ban/jail.local" /etc/fail2ban/jail.local
  mkdir -p /etc/fail2ban/filter.d
  cp "${PROJECT_DIR}/infra/security/fail2ban/filter.d/caddy-badbots.conf" /etc/fail2ban/filter.d/caddy-badbots.conf
  systemctl restart fail2ban || true
fi

echo "[7/8] Installing 'devctl' CLI globally..."
# Create virtualenv for devctl
VENV_DIR="/opt/devctl-venv"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
if [ -f "${PROJECT_DIR}/requirements.txt" ]; then
  "${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"
fi

# Create global wrapper script in /usr/local/bin/devctl
cat << 'EOF' > /usr/local/bin/devctl
#!/usr/bin/env bash
export PYTHONPATH="/opt/happy-galileo:${PYTHONPATH}"
export BASE_DOMAIN="${BASE_DOMAIN:-dev-server.datakrib.com}"
export CADDY_ADMIN_API="${CADDY_ADMIN_API:-http://127.0.0.1:2019}"
export DEVCTL_DOCKER_NETWORK="${DEVCTL_DOCKER_NETWORK:-dev-net}"
exec /opt/devctl-venv/bin/python3 /opt/happy-galileo/devctl/cli.py "$@"
EOF

# Symlink project to /opt/happy-galileo if running elsewhere
if [ "${PROJECT_DIR}" != "/opt/happy-galileo" ]; then
  mkdir -p /opt
  ln -sfn "${PROJECT_DIR}" /opt/happy-galileo
fi

chmod +x /usr/local/bin/devctl
chmod +x "${PROJECT_DIR}/devctl/cli.py"

echo "[8/8] Starting Infrastructure Stack (Caddy + AI-Ops + Status Dashboard)..."
if [ -f "${PROJECT_DIR}/infra/security/proxy_resolver.sh" ]; then
  bash "${PROJECT_DIR}/infra/security/proxy_resolver.sh" "${BASE_DOMAIN}"
fi

cd "${PROJECT_DIR}/infra"
if [ -f "${PROJECT_DIR}/infra/.env" ]; then
  docker compose -f docker-compose.infra.yml --env-file .env up -d
else
  docker compose -f docker-compose.infra.yml up -d
fi

echo ""
echo "========================================================"
echo "🎉 AI Remote Workstation Setup Complete!"
echo "========================================================"
echo "• Public Wildcard:     *.${BASE_DOMAIN}"
echo "• Status Dashboard:    https://status.${BASE_DOMAIN}"
echo "• Internal Network:    dev-net (Zero public ports on apps)"
echo "• devctl CLI:          Installed at /usr/local/bin/devctl"
echo "========================================================"
echo ""

# Run doctor diagnostic
devctl doctor
