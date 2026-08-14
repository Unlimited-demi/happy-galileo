#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Chaos API — AI-Ops & OpenCode Stress Test Runner
# Triggers deliberate faults, logs errors, tests AI-Ops detection,
# creates an Incident Dossier, and demonstrates OpenCode dispatch.
# ═══════════════════════════════════════════════════════════════

API_URL="${1:-https://chaos-api.dev-server.datakrib.com}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    CHAOS API — AI-OPS STRESS TEST & HANDOFF RUNNER       ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Target: $API_URL"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────
# Phase 0: Verify API is alive
# ─────────────────────────────────────────────
echo -e "${CYAN}[Phase 0] Verifying API is online...${NC}"
HEALTH=$(curl -k -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null)
if [ "$HEALTH" != "200" ]; then
    echo -e "${RED}[FAIL] API not reachable (HTTP $HEALTH). Is the container running?${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] API is healthy (HTTP 200)${NC}"
echo ""

# ─────────────────────────────────────────────
# Phase 1: Baseline Normal Operations
# ─────────────────────────────────────────────
echo -e "${CYAN}[Phase 1] Running normal baseline operations...${NC}"

echo "  Creating user..."
curl -k -s -X POST "$API_URL/api/users" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alex Rivers","email":"alex@chaos.io","role":"developer"}' | head -c 120
echo ""

echo "  Listing tasks..."
curl -k -s "$API_URL/api/tasks" | head -c 120
echo ""
echo -e "${GREEN}[OK] Baseline operations successful${NC}"
echo ""

# ─────────────────────────────────────────────
# Phase 2: Trigger Bug #1 — Memory Leak
# ─────────────────────────────────────────────
echo -e "${YELLOW}[Phase 2] Triggering Bug #1 — Rapid Analytics Requests (/api/analytics)${NC}"
for i in $(seq 1 30); do
    curl -k -s "$API_URL/api/analytics" > /dev/null 2>&1 &
done
wait
ANALYTICS=$(curl -k -s "$API_URL/api/analytics" 2>/dev/null)
echo "  Payload: $ANALYTICS" | head -c 140
echo ""

# ─────────────────────────────────────────────
# Phase 3: Trigger Bug #2 — Runtime TypeError Exception
# ─────────────────────────────────────────────
echo -e "${RED}[Phase 3] Triggering Bug #2 — Runtime Application Exception (/api/users/999)${NC}"
ERR_RESP=$(curl -k -s "$API_URL/api/users/999" 2>/dev/null)
echo -e "  Server Response: ${YELLOW}$ERR_RESP${NC}"
echo ""

# ─────────────────────────────────────────────
# Phase 4: Wait for AI-Ops Detection Cycle
# ─────────────────────────────────────────────
echo -e "${CYAN}[Phase 4] Waiting 20s for AI-Ops autonomous monitoring cycle...${NC}"
for i in $(seq 20 -1 1); do
    echo -ne "  Inspecting container logs & probes in ${i}s... \r"
    sleep 1
done
echo ""

# ─────────────────────────────────────────────
# Phase 5: Inspect AI-Ops Incident & Dispatch to OpenCode
# ─────────────────────────────────────────────
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}📋 [AI-OPS MONITORING REPORT]${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
devctl incident list

echo ""
echo -e "${CYAN}[*] Dispatching incident handoff to OpenCode...${NC}"
devctl dispatch
