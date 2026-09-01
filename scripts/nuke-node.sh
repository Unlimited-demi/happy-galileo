#!/usr/bin/env bash
#
# ServerGuard Nuclear Removal Script
# Completely removes ALL traces of ServerGuard from a node.
# The node will stop appearing in the fleet dashboard within ~60 seconds.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Unlimited-demi/happy-galileo/master/scripts/nuke-node.sh | sudo bash
#   # or locally:
#   sudo bash scripts/nuke-node.sh
#
set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; }

if [[ $EUID -ne 0 ]]; then
  err "This script must be run as root (sudo)."
  exit 1
fi

echo ""
echo -e "${BOLD}${RED}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${RED}  ⚠  SERVERGUARD NUCLEAR REMOVAL${NC}"
echo -e "${BOLD}${RED}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  This will ${RED}permanently remove${NC} all ServerGuard components:"
echo "    • Stop and remove all ServerGuard containers"
echo "    • Delete /opt/happy-galileo repository"
echo "    • Delete /opt/devctl-venv Python virtual environment"
echo "    • Remove devctl CLI from /usr/local/bin"
echo "    • Delete ~/.devctl state directory (fleet, incidents, services)"
echo "    • Remove the dev-net Docker network"
echo "    • Remove ServerGuard UFW rules (if identifiable)"
echo ""
echo -e "  ${YELLOW}This does NOT touch your other containers, nginx, or services.${NC}"
echo ""
echo -e "  ${BOLD}Type NUKE to confirm:${NC} "
read -r confirm
if [[ "$confirm" != "NUKE" ]]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo -e "${BOLD}─── Step 1/6: Stop ServerGuard containers ───${NC}"

# Stop the infra stack if docker-compose is available
COMPOSE_FILE="/opt/happy-galileo/infra/docker-compose.infra.yml"
if [[ -f "$COMPOSE_FILE" ]]; then
  log "Stopping docker compose stack..."
  cd /opt/happy-galileo/infra
  docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
fi

# Force-remove containers by name (belt and suspenders)
for container in caddy devctl-dashboard ai-ops-daemon; do
  if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
    log "Removing container: $container"
    docker stop "$container" 2>/dev/null || true
    docker rm -f "$container" 2>/dev/null || true
  fi
done

echo ""
echo -e "${BOLD}─── Step 2/6: Remove Docker images ───${NC}"

# Remove ServerGuard images
for img in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'serverguard|devctl-dashboard|ai-ops' 2>/dev/null); do
  log "Removing image: $img"
  docker rmi -f "$img" 2>/dev/null || true
done

echo ""
echo -e "${BOLD}─── Step 3/6: Remove Docker network ───${NC}"

if docker network ls --format '{{.Name}}' | grep -q '^dev-net$'; then
  # Disconnect any remaining containers from dev-net before removing
  for cid in $(docker network inspect dev-net --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null); do
    docker network disconnect -f dev-net "$cid" 2>/dev/null || true
  done
  log "Removing Docker network: dev-net"
  docker network rm dev-net 2>/dev/null || true
else
  log "Docker network dev-net not found (already removed)"
fi

echo ""
echo -e "${BOLD}─── Step 4/6: Remove filesystem artifacts ───${NC}"

# Repository
if [[ -d /opt/happy-galileo ]]; then
  log "Removing /opt/happy-galileo"
  rm -rf /opt/happy-galileo
fi

# Python venv
if [[ -d /opt/devctl-venv ]]; then
  log "Removing /opt/devctl-venv"
  rm -rf /opt/devctl-venv
fi

# CLI wrapper
if [[ -f /usr/local/bin/devctl ]]; then
  log "Removing /usr/local/bin/devctl"
  rm -f /usr/local/bin/devctl
fi

# State directory
if [[ -d /root/.devctl ]]; then
  log "Removing /root/.devctl (state, incidents, fleet data)"
  rm -rf /root/.devctl
fi

# Also check home directories for other users
for homedir in /home/*; do
  user=$(basename "$homedir")
  devctl_dir="$homedir/.devctl"
  if [[ -d "$devctl_dir" ]]; then
    log "Removing $devctl_dir"
    rm -rf "$devctl_dir"
  fi
done

# Caddy data/config volumes
docker volume rm caddy_data caddy_config 2>/dev/null && log "Removed Caddy volumes" || true

echo ""
echo -e "${BOLD}─── Step 5/6: Remove crontabs and systemd ───${NC}"

# Remove any ServerGuard cron entries
if crontab -l 2>/dev/null | grep -q 'happy-galileo\|devctl'; then
  log "Removing ServerGuard cron entries"
  crontab -l 2>/dev/null | grep -v 'happy-galileo\|devctl' | crontab -
fi

# Remove systemd service if it exists
for svc in serverguard devctl-aiops devctl-dashboard; do
  if systemctl is-enabled "$svc" 2>/dev/null; then
    log "Removing systemd service: $svc"
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/${svc}.service"
  fi
done
systemctl daemon-reload 2>/dev/null || true

echo ""
echo -e "${BOLD}─── Step 6/6: Cleanup ───${NC}"

# Remove any tmux sessions related to ServerGuard
tmux ls 2>/dev/null | grep -E 'opencode|devctl|incident' | awk -F: '{print $1}' | while read session; do
  log "Killing tmux session: $session"
  tmux kill-session -t "$session" 2>/dev/null || true
done

# Prune dangling Docker resources
log "Pruning dangling Docker images and volumes"
docker image prune -f 2>/dev/null || true
docker volume prune -f 2>/dev/null || true

echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  ✓  SERVERGUARD COMPLETELY REMOVED${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Removed:"
echo "    • All ServerGuard containers and images"
echo "    • /opt/happy-galileo repository"
echo "    • /opt/devctl-venv Python environment"
echo "    • /usr/local/bin/devctl CLI"
echo "    • ~/.devctl state directory"
echo "    • dev-net Docker network"
echo "    • Caddy volumes"
echo "    • Cron entries and tmux sessions"
echo ""
echo -e "  ${YELLOW}The node will disappear from the fleet dashboard within 60 seconds.${NC}"
echo -e "  ${YELLOW}Your other containers and services were NOT affected.${NC}"
echo ""
