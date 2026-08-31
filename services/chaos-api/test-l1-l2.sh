#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# L1/L2 Escalation Path Test
# Tests that the AI-Ops daemon can:
#   L1: Detect a stopped container and auto-restart it
#   L2: Detect a detached container and re-attach + reload proxy
# ═══════════════════════════════════════════════════════════════

CONTAINER="${1:-chaos-api}"
NETWORK="${2:-dev-net}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    L1/L2 ESCALATION PATH TEST                            ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Target Container: ${CONTAINER}"
echo "║  Network:          ${NETWORK}"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Verify container is running ──
echo -e "${CYAN}[Pre-check] Verifying ${CONTAINER} is running...${NC}"
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo -e "${RED}[FAIL] Container '${CONTAINER}' not found. Start it first.${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] ${CONTAINER} is running${NC}"
echo ""

# ═══════════════════════════════════════════
# TEST 1: L1 — Container Stop Detection
# ═══════════════════════════════════════════
echo -e "${BOLD}═══ TEST 1: L1 Auto-Restart (Container Stop) ═══${NC}"
echo ""
echo -e "${YELLOW}[L1] Stopping ${CONTAINER}...${NC}"
docker stop "${CONTAINER}"
echo "  Container stopped at $(date -u +%H:%M:%S)"
echo ""
echo -e "${CYAN}[L1] Waiting 25s for AI-Ops to detect and restart...${NC}"

RESTARTED=false
for i in $(seq 25 -1 1); do
    # Check if container is running again
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
        RESTARTED=true
        echo -e "\n${GREEN}[PASS] L1 SUCCESS: ${CONTAINER} was auto-restarted by AI-Ops!${NC}"
        break
    fi
    echo -ne "  Waiting for daemon cycle... ${i}s remaining\r"
    sleep 1
done
echo ""

if [ "$RESTARTED" = false ]; then
    echo -e "${RED}[FAIL] L1 FAILED: ${CONTAINER} was NOT auto-restarted within 25s${NC}"
    echo "  Checking daemon logs for clues..."
    docker logs ai-ops-daemon --tail 10 2>&1 | grep -i "${CONTAINER}" || echo "  No mentions of ${CONTAINER} in daemon logs"
    echo ""
    echo "  Manually restarting for next test..."
    docker start "${CONTAINER}"
fi

# Check daemon logs for L1 evidence
echo ""
echo -e "${CYAN}[L1] Daemon log evidence:${NC}"
docker logs ai-ops-daemon --tail 20 2>&1 | grep -i -E "level 1|restart|${CONTAINER}|unhealthy" | tail -5 || echo "  No L1 entries found"

sleep 5

# ═══════════════════════════════════════════
# TEST 2: L2 — Network Detachment Detection
# ═══════════════════════════════════════════
echo ""
echo -e "${BOLD}═══ TEST 2: L2 Network Re-attach (Container Detach) ═══${NC}"
echo ""

# Verify container is on the network first
ON_NET=$(docker inspect "${CONTAINER}" --format '{{json .NetworkSettings.Networks}}' 2>/dev/null | grep -c "${NETWORK}" || true)
if [ "$ON_NET" = "0" ]; then
    echo -e "${YELLOW}[SKIP] ${CONTAINER} is not on ${NETWORK}. Connecting first...${NC}"
    docker network connect "${NETWORK}" "${CONTAINER}" 2>/dev/null || true
    sleep 2
fi

echo -e "${YELLOW}[L2] Disconnecting ${CONTAINER} from ${NETWORK}...${NC}"
docker network disconnect "${NETWORK}" "${CONTAINER}" 2>/dev/null || true
echo "  Container detached at $(date -u +%H:%M:%S)"
echo ""
echo -e "${CYAN}[L2] Waiting 25s for AI-Ops to detect and re-attach...${NC}"

REATTACHED=false
for i in $(seq 25 -1 1); do
    ON_NET=$(docker inspect "${CONTAINER}" --format '{{json .NetworkSettings.Networks}}' 2>/dev/null | grep -c "${NETWORK}" || true)
    if [ "$ON_NET" != "0" ]; then
        REATTACHED=true
        echo -e "\n${GREEN}[PASS] L2 SUCCESS: ${CONTAINER} was re-attached to ${NETWORK} by AI-Ops!${NC}"
        break
    fi
    echo -ne "  Waiting for daemon cycle... ${i}s remaining\r"
    sleep 1
done
echo ""

if [ "$REATTACHED" = false ]; then
    echo -e "${RED}[FAIL] L2 FAILED: ${CONTAINER} was NOT re-attached within 25s${NC}"
    echo "  Checking daemon logs..."
    docker logs ai-ops-daemon --tail 10 2>&1 | grep -i "${CONTAINER}" || echo "  No mentions of ${CONTAINER} in daemon logs"
    echo ""
    echo "  Manually re-attaching..."
    docker network connect "${NETWORK}" "${CONTAINER}" 2>/dev/null || true
fi

# Check daemon logs for L2 evidence
echo ""
echo -e "${CYAN}[L2] Daemon log evidence:${NC}"
docker logs ai-ops-daemon --tail 20 2>&1 | grep -i -E "level 2|reattach|network|${CONTAINER}|proxy" | tail -5 || echo "  No L2 entries found"

echo ""
echo -e "${BOLD}═══ RESULTS ═══${NC}"
echo -e "  L1 (Auto-Restart):     $([ "$RESTARTED" = true ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
echo -e "  L2 (Network Re-attach): $([ "$REATTACHED" = true ] && echo -e "${GREEN}PASS${NC}" || echo -e "${RED}FAIL${NC}")"
echo ""
