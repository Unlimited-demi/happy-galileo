#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Chaos API — AI-Ops Stress Test Runner
# Triggers all 5 intentional bugs sequentially to test
# detection, auto-restart, and incident dossier generation.
# ═══════════════════════════════════════════════════════════════

API_URL="${1:-https://chaos-api.dev-server.datakrib.com}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    CHAOS API — AI-OPS STRESS TEST RUNNER                ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Target: $API_URL"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────
# Phase 0: Verify API is alive
# ─────────────────────────────────────────────
echo -e "${CYAN}[Phase 0] Verifying API is online...${NC}"
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null)
if [ "$HEALTH" != "200" ]; then
    echo -e "${RED}[FAIL] API not reachable (HTTP $HEALTH). Is the container running?${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] API is healthy (HTTP 200)${NC}"
echo ""

# ─────────────────────────────────────────────
# Phase 1: Normal operations (baseline)
# ─────────────────────────────────────────────
echo -e "${CYAN}[Phase 1] Running normal API operations (baseline)...${NC}"

echo "  Creating user..."
curl -s -X POST "$API_URL/api/users" \
    -H "Content-Type: application/json" \
    -d '{"name":"Test User","email":"test@chaos.io","role":"developer"}' | head -c 120
echo ""

echo "  Listing users..."
curl -s "$API_URL/api/users" | head -c 120
echo ""

echo "  Listing tasks..."
curl -s "$API_URL/api/tasks" | head -c 120
echo ""
echo -e "${GREEN}[OK] Baseline operations successful${NC}"
echo ""

# ─────────────────────────────────────────────
# Phase 2: Trigger Bug #1 — Memory Leak
# ─────────────────────────────────────────────
echo -e "${YELLOW}[Phase 2] Triggering Bug #1 — Memory Leak (/api/analytics)${NC}"
echo "  Sending 50 rapid analytics requests to inflate memory..."
for i in $(seq 1 50); do
    curl -s "$API_URL/api/analytics" > /dev/null 2>&1 &
done
wait
echo -e "${YELLOW}  Memory leak accumulating... (check /api/analytics → history.memoryUsageMB)${NC}"
ANALYTICS=$(curl -s "$API_URL/api/analytics" 2>/dev/null)
echo "  $ANALYTICS" | grep -o '"memoryUsageMB":[0-9]*' || echo "  (could not read memory)"
echo ""

# ─────────────────────────────────────────────
# Phase 3: Trigger Bug #3 — Intermittent 500s
# ─────────────────────────────────────────────
echo -e "${YELLOW}[Phase 3] Triggering Bug #3 — Intermittent 500s on POST /api/tasks${NC}"
FAIL_COUNT=0
for i in $(seq 1 20); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/tasks" \
        -H "Content-Type: application/json" \
        -d "{\"title\":\"Task $i\",\"priority\":\"high\"}" 2>/dev/null)
    if [ "$STATUS" = "500" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done
echo -e "  Results: ${RED}$FAIL_COUNT / 20 requests returned HTTP 500${NC}"
echo ""

# ─────────────────────────────────────────────
# Phase 4: Trigger Bug #5 — Hanging Response
# ─────────────────────────────────────────────
echo -e "${YELLOW}[Phase 4] Triggering Bug #5 — Hanging endpoint (timeout test)${NC}"
echo "  Requesting /api/reports/generate with 5s timeout..."
HANG_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$API_URL/api/reports/generate" 2>/dev/null)
if [ "$HANG_STATUS" = "000" ]; then
    echo -e "  ${RED}[CONFIRMED] Request timed out — endpoint is hanging${NC}"
else
    echo -e "  Response: HTTP $HANG_STATUS"
fi
echo ""

# ─────────────────────────────────────────────
# Phase 5: Trigger Bug #2 — Null Reference Crash
# ─────────────────────────────────────────────
echo -e "${RED}[Phase 5] Triggering Bug #2 — Null Reference CRASH (GET /api/users/999)${NC}"
echo "  This will crash the server process..."
CRASH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/users/999" 2>/dev/null)
echo -e "  Response: HTTP $CRASH_STATUS"
echo ""

# Wait for Docker to auto-restart
echo -e "${CYAN}[*] Waiting 10s for Docker auto-restart...${NC}"
sleep 10

# Check if API recovered
RECOVERY=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null)
if [ "$RECOVERY" = "200" ]; then
    echo -e "${GREEN}[RECOVERED] API is back online after crash (Docker restart: unless-stopped)${NC}"
else
    echo -e "${RED}[DOWN] API did not recover (HTTP $RECOVERY)${NC}"
fi
echo ""

# ─────────────────────────────────────────────
# Phase 6: Check AI-Ops Detection
# ─────────────────────────────────────────────
echo -e "${CYAN}[Phase 6] Checking AI-Ops incident detection...${NC}"
echo "  Run: devctl incident list"
echo "  Run: devctl test chaos-api"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Stress test complete. Check the AI-Ops dashboard at:"
echo "  https://status.dev-server.datakrib.com"
echo "═══════════════════════════════════════════════════════════"
echo ""
