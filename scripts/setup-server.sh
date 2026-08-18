#!/usr/bin/env bash
# ==============================================================================
# Full Turnkey Bootstrap Script for AI Remote Workstation
# Configures: Docker, Caddy, Fail2ban, UFW, Node/Playwright, OpenCode, devctl
# Domain Scope: *.dev-server.datakrib.com
# ==============================================================================

set -e

# Parse optional arguments
BASE_DOMAIN="${BASE_DOMAIN:-dev-server.datakrib.com}"
GIT_NAME="${GIT_NAME:-}"
GIT_EMAIL="${GIT_EMAIL:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --domain) BASE_DOMAIN="$2"; shift ;;
    --git-name|--git-username) GIT_NAME="$2"; shift ;;
    --git-email) GIT_EMAIL="$2"; shift ;;
    --github-token|--token) GITHUB_TOKEN="$2"; shift ;;
    *) echo "Unknown parameter: $1"; exit 1 ;;
  esac
  shift
done

echo "========================================================"
echo "🚀 Bootstrapping AI Remote Development Workstation"
echo "   Domain Scope: *.${BASE_DOMAIN}"
echo "   GitHub Auth:  ${GITHUB_TOKEN:+Token (Zero-Touch)}${GITHUB_TOKEN:-SSH Key}"
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
  jq \
  openssh-client

# ── Git Identity & Authentication Setup ──
echo "[*] Configuring Git identity..."
if [ -n "${GIT_NAME}" ]; then
  git config --global user.name "${GIT_NAME}"
elif [ -z "$(git config --global user.name 2>/dev/null)" ]; then
  git config --global user.name "OpenCode Server"
fi

if [ -n "${GIT_EMAIL}" ]; then
  git config --global user.email "${GIT_EMAIL}"
elif [ -z "$(git config --global user.email 2>/dev/null)" ]; then
  git config --global user.email "bot@datakrib.com"
fi

# Method A: GitHub Token (Zero-Touch)
if [ -n "${GITHUB_TOKEN}" ]; then
  echo "[*] Configuring Git with GitHub Personal Access Token (Zero-Touch)..."
  git config --global credential.helper store
  echo "https://${GITHUB_TOKEN}:x-oauth-basic@github.com" > "${HOME}/.git-credentials"
  chmod 600 "${HOME}/.git-credentials"
  git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
  git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "git@github.com:"
  echo "  [✓] GitHub Token configured successfully. Zero manual SSH steps required!"

# Method B: SSH Key generation
else
  echo "[*] Setting up GitHub SSH deploy key..."
  SSH_DIR="${HOME}/.ssh"
  mkdir -p "${SSH_DIR}"
  chmod 700 "${SSH_DIR}"

  if [ ! -f "${SSH_DIR}/id_ed25519" ]; then
    echo "  Generating ED25519 SSH Key..."
    ssh-keygen -t ed25519 -C "${GIT_EMAIL:-server@datakrib.com}" -f "${SSH_DIR}/id_ed25519" -N ""
  fi

  # Pre-populate known_hosts for github.com
  ssh-keyscan -t ed25519,rsa github.com >> "${SSH_DIR}/known_hosts" 2>/dev/null || true
  chmod 600 "${SSH_DIR}/known_hosts" 2>/dev/null || true
fi

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
if [ -f "${PROJECT_DIR}/infra/security/ufw_setup.sh" ]; then
  bash "${PROJECT_DIR}/infra/security/ufw_setup.sh"
else
  # Basic firewall setup if custom script not yet created
  ufw --force enable 2>/dev/null || true
  ufw allow 22/tcp 2>/dev/null || true
  ufw allow 80/tcp 2>/dev/null || true
  ufw allow 443/tcp 2>/dev/null || true
  echo "  [i] Using default UFW rules (custom ufw_setup.sh not found)"
fi

if [ -d "/etc/fail2ban" ]; then
  if [ -f "${PROJECT_DIR}/infra/security/fail2ban/jail.local" ]; then
    cp "${PROJECT_DIR}/infra/security/fail2ban/jail.local" /etc/fail2ban/jail.local
    mkdir -p /etc/fail2ban/filter.d
    if [ -f "${PROJECT_DIR}/infra/security/fail2ban/filter.d/caddy-badbots.conf" ]; then
      cp "${PROJECT_DIR}/infra/security/fail2ban/filter.d/caddy-badbots.conf" /etc/fail2ban/filter.d/caddy-badbots.conf
    fi
    systemctl restart fail2ban || true
  else
    echo "  [i] Fail2ban installed but no custom jail config found — using defaults"
  fi
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
cd "${PROJECT_DIR}/infra"

# Auto-generate .env from template if missing
if [ ! -f ".env" ] && [ -f "${PROJECT_DIR}/.env.example" ]; then
  echo "  [i] Creating infra/.env from .env.example..."
  sed "s/dev-server.datakrib.com/${BASE_DOMAIN}/g" "${PROJECT_DIR}/.env.example" > .env
fi

if [ -n "${GITHUB_TOKEN}" ]; then
  echo "GITHUB_TOKEN=${GITHUB_TOKEN}" >> .env
fi

# Detect existing host web servers (Nginx/Apache/Caddy) and set internal ports if needed
if [ -f "${PROJECT_DIR}/infra/security/proxy_resolver.sh" ]; then
  bash "${PROJECT_DIR}/infra/security/proxy_resolver.sh" "${BASE_DOMAIN}"
fi

docker compose -f docker-compose.infra.yml up -d --build

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

# ── Print SSH Deploy Key for GitHub ──
if [ -f "${HOME}/.ssh/id_ed25519.pub" ]; then
  PUB_KEY="$(cat "${HOME}/.ssh/id_ed25519.pub")"
  echo ""
  echo "╔══════════════════════════════════════════════════════════════════════╗"
  echo "║ 🔑 GITHUB SSH PUBLIC KEY FOR THIS SERVER                             ║"
  echo "╠══════════════════════════════════════════════════════════════════════╣"
  echo ""
  echo "  ${PUB_KEY}"
  echo ""
  echo "  👉 Add this key to GitHub so OpenCode can checkout & push fix branches:"
  echo "     1. Go to: https://github.com/settings/keys"
  echo "        (or repo Deploy Keys: https://github.com/Unlimited-demi/happy-galileo/settings/keys)"
  echo "     2. Click 'New SSH Key' (Title: serverguard-primary)"
  echo "     3. Paste the key above (check 'Allow write access' if Deploy Key)"
  echo ""
  echo "╚══════════════════════════════════════════════════════════════════════╝"
  echo ""
fi
