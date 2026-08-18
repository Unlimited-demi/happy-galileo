#!/usr/bin/env bash
# ==============================================================================
# NODE AGENT Setup Script (for remote servers joining the fleet)
# Purpose: Sets up a REMOTE server to be monitored by the Central Hub.
#          Installs AI-Ops agent, devctl, OpenCode, auto-discovers existing
#          containers, and streams telemetry to the Central Fleet Dashboard.
#
# What it installs:
#   - Docker & Docker Compose (if not present)
#   - Node.js & Playwright (for visual testing)
#   - OpenCode CLI (autonomous code remediation agent)
#   - devctl CLI (service management)
#   - Caddy reverse proxy (internal, respects existing Nginx/Apache/Mailcow)
#   - AI-Ops monitoring daemon (container state + log scanning)
#   - Fleet Telemetry Streamer (streams health data to Central Hub)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Unlimited-demi/happy-galileo/master/scripts/setup-node.sh | \
#     sudo bash -s -- \
#       --node-name "vm2" \
#       --domain "vm2.dev-server.datakrib.com" \
#       --hub-url "https://status.dev-server.datakrib.com/api/telemetry/ingest"
# ==============================================================================

set -e

NODE_NAME="${NODE_NAME:-$(hostname -s)}"
BASE_DOMAIN="${BASE_DOMAIN:-dev-server.datakrib.com}"
CENTRAL_HUB_URL="${CENTRAL_HUB_URL:-}"
FLEET_KEY="${FLEET_KEY:-default-fleet-key}"
GIT_NAME="${GIT_NAME:-}"
GIT_EMAIL="${GIT_EMAIL:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
INSTALL_DIR="/opt/happy-galileo"
REPO_URL="https://github.com/Unlimited-demi/happy-galileo.git"
REPO_SSH_URL="git@github.com:Unlimited-demi/happy-galileo.git"
REPO_HTTPS_URL="https://github.com/Unlimited-demi/happy-galileo.git"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --node-name) NODE_NAME="$2"; shift ;;
    --domain) BASE_DOMAIN="$2"; shift ;;
    --hub-url) CENTRAL_HUB_URL="$2"; shift ;;
    --fleet-key) FLEET_KEY="$2"; shift ;;
    --git-name|--git-username) GIT_NAME="$2"; shift ;;
    --git-email) GIT_EMAIL="$2"; shift ;;
    --github-token|--token) GITHUB_TOKEN="$2"; shift ;;
    *) echo "Unknown parameter: $1"; exit 1 ;;
  esac
  shift
done

echo "========================================================"
echo "📡 Setting up FLEET NODE AGENT: ${NODE_NAME}"
echo "   Domain Scope:     *.${BASE_DOMAIN}"
echo "   Central Hub:      ${CENTRAL_HUB_URL:-None (Standalone)}"
echo "   Role:             NODE AGENT (Monitor + Stream Telemetry)"
echo "   GitHub Auth:      ${GITHUB_TOKEN:+Token (Zero-Touch)}${GITHUB_TOKEN:-SSH Key}"
echo "========================================================"

if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
export BASE_DOMAIN

# ── Step 1: Prerequisites ──
echo "[1/8] Installing prerequisites..."
apt-get update -y
apt-get install -y \
  apt-transport-https \
  ca-certificates \
  curl \
  gnupg \
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
  git config --global user.name "${NODE_NAME}-agent"
fi

if [ -n "${GIT_EMAIL}" ]; then
  git config --global user.email "${GIT_EMAIL}"
elif [ -z "$(git config --global user.email 2>/dev/null)" ]; then
  git config --global user.email "bot@datakrib.com"
fi

# Method A: GitHub Token (Zero-Touch, No SSH key copying needed!)
if [ -n "${GITHUB_TOKEN}" ]; then
  echo "[*] Configuring Git with GitHub Personal Access Token (Zero-Touch)..."
  git config --global credential.helper store
  echo "https://${GITHUB_TOKEN}:x-oauth-basic@github.com" > "${HOME}/.git-credentials"
  chmod 600 "${HOME}/.git-credentials"
  git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
  git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "git@github.com:"
  echo "  [✓] GitHub Token configured successfully. Zero manual SSH steps required!"

# Method B: SSH Key generation & authorization
else
  echo "[*] Setting up GitHub SSH deploy key..."
  SSH_DIR="${HOME}/.ssh"
  mkdir -p "${SSH_DIR}"
  chmod 700 "${SSH_DIR}"

  if [ ! -f "${SSH_DIR}/id_ed25519" ]; then
    echo "  Generating ED25519 SSH Key..."
    ssh-keygen -t ed25519 -C "${GIT_EMAIL:-node-${NODE_NAME}@datakrib.com}" -f "${SSH_DIR}/id_ed25519" -N ""
  fi

  # Pre-populate known_hosts for github.com
  ssh-keyscan -t ed25519,rsa github.com >> "${SSH_DIR}/known_hosts" 2>/dev/null || true
  chmod 600 "${SSH_DIR}/known_hosts" 2>/dev/null || true

  # Check GitHub SSH access
  echo "[*] Verifying GitHub SSH Access for private repository..."
  ssh_auth_ok=false
  if ssh -T git@github.com -o StrictHostKeyChecking=accept-new -o BatchMode=yes 2>&1 | grep -E -q "successfully authenticated|You've successfully"; then
    ssh_auth_ok=true
    echo "  [✓] GitHub SSH Authentication verified!"
  fi

  if [ "$ssh_auth_ok" = false ]; then
    PUB_KEY="$(cat "${SSH_DIR}/id_ed25519.pub")"
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║ 🔑 GITHUB SSH KEY REQUIRED FOR PRIVATE REPO ACCESS                   ║"
    echo "╠══════════════════════════════════════════════════════════════════════╣"
    echo ""
    echo "  ${PUB_KEY}"
    echo ""
    echo "  👉 Please add this SSH key to GitHub now:"
    echo "     1. Go to: https://github.com/settings/keys"
    echo "        (or repo: https://github.com/Unlimited-demi/happy-galileo/settings/keys)"
    echo "     2. Click 'New SSH Key' (Title: ${NODE_NAME}-server)"
    echo "     3. Paste the key above (check 'Allow write access' if Deploy Key)"
    echo ""
    echo "  💡 TIP: Avoid this step on future servers by passing --github-token <token>!"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "⏳ Waiting for GitHub authorization (checking automatically every 5s)..."
    while [ "$ssh_auth_ok" = false ]; do
      sleep 5
      if ssh -T git@github.com -o StrictHostKeyChecking=accept-new -o BatchMode=yes 2>&1 | grep -E -q "successfully authenticated|You've successfully"; then
        ssh_auth_ok=true
        echo ""
        echo "  [✓] GitHub SSH Key verified and authorized! Proceeding with clone..."
        echo ""
        break
      fi
    done
  fi
fi

# ── Step 2: Docker ──
echo "[2/8] Installing Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh
  rm get-docker.sh
  systemctl enable docker
  systemctl start docker
fi
apt-get install -y docker-compose-plugin 2>/dev/null || true

# ── Step 3: Clone Codebase ──
if [ -n "${GITHUB_TOKEN}" ]; then
  TARGET_CLONE_URL="https://${GITHUB_TOKEN}@github.com/Unlimited-demi/happy-galileo.git"
  echo "[3/8] Fetching workstation codebase via GitHub Token..."
else
  TARGET_CLONE_URL="${REPO_SSH_URL}"
  echo "[3/8] Fetching workstation codebase via SSH..."
fi

if [ ! -d "${INSTALL_DIR}" ]; then
  mkdir -p /opt
  if ! git clone "${TARGET_CLONE_URL}" "${INSTALL_DIR}"; then
    echo "  [i] Clone failed, retrying via HTTPS fallback..."
    git clone "${REPO_HTTPS_URL}" "${INSTALL_DIR}"
  fi
else
  cd "${INSTALL_DIR}"
  git remote set-url origin "${TARGET_CLONE_URL}" 2>/dev/null || true
  git fetch origin master
  git reset --hard origin/master || true
fi

# ── Step 4: Node.js + OpenCode ──
echo "[4/8] Installing Node.js, Playwright & OpenCode..."
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

cd "${INSTALL_DIR}"
if [ -f "package.json" ]; then
  npm install 2>/dev/null || true
  npx playwright install-deps chromium 2>/dev/null || true
  npx playwright install chromium 2>/dev/null || true
fi

# Install OpenCode for autonomous remediation
if ! command -v opencode &> /dev/null; then
  echo "[*] Installing OpenCode CLI..."
  npm install -g opencode-ai 2>/dev/null || npm install -g @opencode/cli 2>/dev/null || echo "[!] OpenCode not found in npm. Install manually."
fi

# ── Step 5: Docker network ──
echo "[5/8] Creating internal Docker network 'dev-net'..."
docker network inspect dev-net &>/dev/null || docker network create dev-net

# ── Step 6: devctl CLI ──
echo "[6/8] Installing devctl CLI..."
VENV_DIR="/opt/devctl-venv"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
if [ -f "${INSTALL_DIR}/requirements.txt" ]; then
  "${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
fi

cat << EOF > /usr/local/bin/devctl
#!/usr/bin/env bash
export PYTHONPATH="/opt/happy-galileo:\${PYTHONPATH}"
export BASE_DOMAIN="\${BASE_DOMAIN:-${BASE_DOMAIN}}"
export NODE_NAME="\${NODE_NAME:-${NODE_NAME}}"
export CENTRAL_HUB_URL="\${CENTRAL_HUB_URL:-${CENTRAL_HUB_URL}}"
export FLEET_KEY="\${FLEET_KEY:-${FLEET_KEY}}"
export CADDY_ADMIN_API="\${CADDY_ADMIN_API:-http://127.0.0.1:2019}"
export DEVCTL_DOCKER_NETWORK="\${DEVCTL_DOCKER_NETWORK:-dev-net}"
exec /opt/devctl-venv/bin/python3 /opt/happy-galileo/devctl/cli.py "\$@"
EOF
chmod +x /usr/local/bin/devctl
chmod +x "${INSTALL_DIR}/devctl/cli.py"

# ── Step 7: Configure Environment & Resolve Proxy Conflicts ──
echo "[7/8] Configuring environment, resolving proxy conflicts & hardening firewall..."

# Write initial node .env with telemetry and credentials
cat << EOF > "${INSTALL_DIR}/infra/.env"
BASE_DOMAIN=${BASE_DOMAIN}
NODE_NAME=${NODE_NAME}
CENTRAL_HUB_URL=${CENTRAL_HUB_URL}
FLEET_KEY=${FLEET_KEY}
GITHUB_TOKEN=${GITHUB_TOKEN}
EOF

# Detect existing host web servers (Nginx/Apache/Caddy) and set internal ports if needed
if [ -f "${INSTALL_DIR}/infra/security/proxy_resolver.sh" ]; then
  bash "${INSTALL_DIR}/infra/security/proxy_resolver.sh" "${BASE_DOMAIN}"
fi

# Harden firewall
if [ -f "${INSTALL_DIR}/infra/security/ufw_setup.sh" ]; then
  bash "${INSTALL_DIR}/infra/security/ufw_setup.sh" 2>/dev/null || true
fi

# ── Step 8: Start Infrastructure ──
echo "[8/8] Starting Node Agent Stack (Caddy + AI-Ops + Dashboard)..."
cd "${INSTALL_DIR}/infra"
docker compose -f docker-compose.infra.yml --env-file .env up -d --build

# ── Auto-discover existing containers ──
echo ""
echo "[*] Auto-discovering existing Docker containers on this server..."
sleep 3
devctl discover 2>/dev/null || true

# ── Send initial heartbeat to Central Hub ──
if [ -n "${CENTRAL_HUB_URL}" ]; then
  echo "[*] Sending initial telemetry heartbeat to Central Hub..."
  devctl heartbeat --name "${NODE_NAME}" --hub "${CENTRAL_HUB_URL}" 2>/dev/null || true
fi

echo ""
echo "========================================================"
echo "🎉 Node Agent Setup Complete: ${NODE_NAME}"
echo "========================================================"
echo "• Role:              NODE AGENT"
echo "• Public Wildcard:   *.${BASE_DOMAIN}"
echo "• Local Dashboard:   https://status.${BASE_DOMAIN}"
echo "• Central Hub:       ${CENTRAL_HUB_URL:-Not configured (standalone)}"
echo "• Internal Network:  dev-net"
echo "• devctl CLI:        /usr/local/bin/devctl"
echo "• OpenCode:          $(command -v opencode 2>/dev/null || echo 'Not installed')"
echo "========================================================"
echo ""
echo "📊 Monitoring: AI-Ops is now watching all containers via:"
echo "   • Docker container state (running/stopped/restarting)"
echo "   • Docker HEALTHCHECK status"
echo "   • Container log scanning for errors & exceptions"
echo "   • OOM kill detection"
echo "   • Restart loop detection"
echo ""

# Run doctor
devctl doctor

# ── Print SSH Deploy Key for GitHub ──
if [ -f "${HOME}/.ssh/id_ed25519.pub" ]; then
  PUB_KEY="$(cat "${HOME}/.ssh/id_ed25519.pub")"
  echo ""
  echo "╔══════════════════════════════════════════════════════════════════════╗"
  echo "║ 🔑 GITHUB SSH PUBLIC KEY FOR THIS SERVER (${NODE_NAME})              ║"
  echo "╠══════════════════════════════════════════════════════════════════════╣"
  echo ""
  echo "  ${PUB_KEY}"
  echo ""
  echo "  👉 Add this key to GitHub so OpenCode can checkout & push fix branches:"
  echo "     1. Go to: https://github.com/settings/keys"
  echo "        (or repo Deploy Keys: https://github.com/Unlimited-demi/happy-galileo/settings/keys)"
  echo "     2. Click 'New SSH Key' (Title: ${NODE_NAME}-server)"
  echo "     3. Paste the key above (check 'Allow write access' if Deploy Key)"
  echo ""
  echo "╚══════════════════════════════════════════════════════════════════════╝"
  echo ""
fi
