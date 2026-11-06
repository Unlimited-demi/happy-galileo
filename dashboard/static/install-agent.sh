#!/usr/bin/env bash
# ==============================================================================
# ARA Autonomous Fleet Agent One-Line Installer
# Installs the lightweight node telemetry & log agent as a persistent systemd service.
#
# Usage:
#   curl -sSL https://ara.suburbancloud.ng/install-agent.sh | sudo bash -s -- \
#     --hub "https://ara.suburbancloud.ng" \
#     --fleet-key "ara_fleet_305dc0e721b5f52d96be99d7b8ee8656e2befa3e" \
#     --node-name "suburban-support-prod"
# ==============================================================================

set -e

HUB_URL="https://ara.suburbancloud.ng"
FLEET_KEY="ara_fleet_305dc0e721b5f52d96be99d7b8ee8656e2befa3e"
NODE_NAME="$(hostname -s 2>/dev/null || echo 'satellite-node')"
BASE_DOMAIN="suburbancloud.ng"
AGENT_DIR="/opt/ara-agent"

while [[ "$#" -gt 0 ]]; do
  case $1 in
    --hub|--hub-url) HUB_URL="$2"; shift ;;
    --fleet-key|--token|--key) FLEET_KEY="$2"; shift ;;
    --node-name|--name) NODE_NAME="$2"; shift ;;
    --domain) BASE_DOMAIN="$2"; shift ;;
    --dir) AGENT_DIR="$2"; shift ;;
    *) echo "Unknown parameter: $1"; exit 1 ;;
  esac
  shift
done

echo "========================================================"
echo "🛰️  ARA Autonomous Fleet Agent Installation"
echo "   Node Name:    ${NODE_NAME}"
echo "   Central Hub:  ${HUB_URL}"
echo "   Target Dir:   ${AGENT_DIR}"
echo "========================================================"

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
  echo "[*] Installing Python 3..."
  if command -v apt-get &> /dev/null; then
    apt-get update -y && apt-get install -y python3
  elif command -v yum &> /dev/null; then
    yum install -y python3
  elif command -v dnf &> /dev/null; then
    dnf install -y python3
  else
    echo "❌ Python 3 is required. Please install python3 first."
    exit 1
  fi
fi

# 2. Check Docker Socket
if [ ! -e /var/run/docker.sock ]; then
  echo "⚠️  Warning: /var/run/docker.sock not found. Make sure Docker is installed and running."
fi

# 3. Create Agent Directory
mkdir -p "${AGENT_DIR}"
chmod 755 "${AGENT_DIR}"

# 4. Write Configuration
cat << EOF > "${AGENT_DIR}/config.env"
HUB_URL=${HUB_URL}
FLEET_KEY=${FLEET_KEY}
NODE_NAME=${NODE_NAME}
BASE_DOMAIN=${BASE_DOMAIN}
EOF
chmod 600 "${AGENT_DIR}/config.env"

# 5. Fetch or write the Python Agent
DOWNLOAD_URL="${HUB_URL%/}/ara-agent.py"
echo "[*] Fetching latest ARA agent script from ${DOWNLOAD_URL}..."
if curl -fsSL "${DOWNLOAD_URL}" -o "${AGENT_DIR}/agent.py" 2>/dev/null; then
  echo "  [✓] Downloaded agent from Central Hub."
else
  echo "  [i] Hub download unavailable, falling back to direct installation..."
  # If running from repository clone or direct script
  if [ -f "$(dirname "$0")/ara-agent.py" ]; then
    cp "$(dirname "$0")/ara-agent.py" "${AGENT_DIR}/agent.py"
  else
    echo "  [!] Attempting GitHub raw download fallback..."
    curl -fsSL "https://raw.githubusercontent.com/Unlimited-demi/happy-galileo/master/scripts/ara-agent.py" -o "${AGENT_DIR}/agent.py" || true
  fi
fi

if [ ! -s "${AGENT_DIR}/agent.py" ]; then
  echo "❌ Failed to download agent.py. Check network or Hub connectivity."
  exit 1
fi
chmod +x "${AGENT_DIR}/agent.py"

# 6. Test Heartbeat & Authentication with Hub
echo "[*] Testing initial telemetry transmission..."
if ! python3 "${AGENT_DIR}/agent.py" \
  --hub "${HUB_URL}" \
  --fleet-key "${FLEET_KEY}" \
  --node-name "${NODE_NAME}" \
  --domain "${BASE_DOMAIN}" \
  --once; then
  echo "❌ Test heartbeat failed. Check your FLEET_KEY or Central Hub URL."
  exit 1
fi
echo "  [✓] Handshake verified! Hub accepted node telemetry."

# 7. Configure Persistent systemd Service
if [ "$EUID" -eq 0 ] && command -v systemctl &> /dev/null; then
  echo "[*] Registering systemd service (/etc/systemd/system/ara-agent.service)..."
  cat << EOF > /etc/systemd/system/ara-agent.service
[Unit]
Description=ARA Autonomous Node Telemetry & Log Agent
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
EnvironmentFile=${AGENT_DIR}/config.env
ExecStart=/usr/bin/python3 ${AGENT_DIR}/agent.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now ara-agent
  systemctl restart ara-agent
  echo "  [✓] Service 'ara-agent' enabled and running via systemd."
else
  # Non-root or no systemd: setup background supervisor
  echo "[!] Non-root execution: starting agent via nohup..."
  pkill -f "${AGENT_DIR}/agent.py" || true
  nohup python3 "${AGENT_DIR}/agent.py" \
    --hub "${HUB_URL}" \
    --fleet-key "${FLEET_KEY}" \
    --node-name "${NODE_NAME}" \
    --domain "${BASE_DOMAIN}" > "${AGENT_DIR}/agent.log" 2>&1 &
  echo "  [✓] Agent running in background (PID: $!)."
fi

echo ""
echo "========================================================"
echo "🎉 ARA Node Enrollment Complete: ${NODE_NAME}"
echo "========================================================"
echo "• Status:          ONLINE & STREAMING (Every 15s)"
echo "• Logs:            Streaming Docker logs (tail 100) per container"
echo "• System Metrics:  CPU, RAM, Disk, Network I/O, Real IP"
echo "• Central Hub:     ${HUB_URL}/dashboard"
echo "========================================================"
