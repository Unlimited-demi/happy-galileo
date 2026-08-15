#!/usr/bin/env bash
# End-to-End Proof Test: AI-Ops Monitoring System
# Run on a live server to prove the system detects and handles failures

set +e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Initialize summary tracking
declare -a TEST_NAMES
declare -a TEST_RESULTS
declare -a TEST_DETAILS
FAILED_TESTS=0

record_result() {
    local name=$1
    local result=$2
    local detail=$3
    
    TEST_NAMES+=("$name")
    if [ "$result" = "PASS" ]; then
        TEST_RESULTS+=("${GREEN}PASS${NC}")
        echo -e "${GREEN}✓ PASS${NC} - $name"
    else
        TEST_RESULTS+=("${RED}FAIL${NC}")
        ((FAILED_TESTS++))
        echo -e "${RED}✗ FAIL${NC} - $name: $detail"
    fi
    TEST_DETAILS+=("$detail")
}

cleanup() {
    echo -e "\n=== Running Cleanup ==="
    docker stop test-crasher test-error-logger test-healthy 2>/dev/null
    docker rm test-crasher test-error-logger test-healthy 2>/dev/null
    devctl hide test-crasher 2>/dev/null
    devctl hide test-error-logger 2>/dev/null
    devctl hide test-healthy 2>/dev/null
    
    # Try to purge test incidents if the command exists, otherwise delete files
    devctl incident purge 2>/dev/null || rm -rf ~/.devctl/incidents/INC-* 2>/dev/null
}
trap cleanup EXIT

echo "=== Starting End-to-End Proof Test ==="

# ---------------------------------------------------------
# Test 1: Crash Detection
# ---------------------------------------------------------
echo -e "\nRunning Test 1: Crash Detection..."
docker run -d --name test-crasher --network dev-net alpine sh -c 'echo FATAL: process crashed && exit 1'
devctl expose test-crasher 80
echo "Waiting 30 seconds for AI-Ops to detect crash..."
sleep 30

CRASH_INCIDENT=$(devctl incident list | grep "test-crasher")
if [ -n "$CRASH_INCIDENT" ]; then
    record_result "Crash Detection" "PASS" "Incident found for test-crasher"
    INCIDENT_ID_1=$(echo "$CRASH_INCIDENT" | grep -o 'INC-[0-9]\{8\}-[A-Z0-9]\{6\}' | head -n 1)
else
    record_result "Crash Detection" "FAIL" "No incident found for test-crasher"
fi

# ---------------------------------------------------------
# Test 2: Error Log Detection
# ---------------------------------------------------------
echo -e "\nRunning Test 2: Error Log Detection..."
docker run -d --name test-error-logger --network dev-net alpine sh -c 'while true; do echo "[ERROR] TypeError: Cannot read properties of undefined" >> /proc/1/fd/1; sleep 2; done'
devctl expose test-error-logger 80
echo "Waiting 30 seconds for AI-Ops to detect log errors..."
sleep 30

LOG_INCIDENT=$(devctl incident list | grep "TypeError")
if [ -n "$LOG_INCIDENT" ]; then
    record_result "Error Log Detection" "PASS" "Incident found with TypeError"
    INCIDENT_ID_2=$(echo "$LOG_INCIDENT" | grep -o 'INC-[0-9]\{8\}-[A-Z0-9]\{6\}' | head -n 1)
else
    record_result "Error Log Detection" "FAIL" "No incident found with TypeError"
fi

# ---------------------------------------------------------
# Test 3: Healthy Container (No False Positive)
# ---------------------------------------------------------
echo -e "\nRunning Test 3: Healthy Container (No False Positive)..."
docker run -d --name test-healthy --network dev-net nginx:alpine
devctl expose test-healthy 80
echo "Waiting 30 seconds..."
sleep 30

HEALTHY_INCIDENT=$(devctl incident list | grep "test-healthy")
if [ -z "$HEALTHY_INCIDENT" ]; then
    record_result "Healthy Container" "PASS" "No incident found for healthy container"
else
    record_result "Healthy Container" "FAIL" "False positive incident found"
fi

# ---------------------------------------------------------
# Test 4: Incident Lifecycle
# ---------------------------------------------------------
echo -e "\nRunning Test 4: Incident Lifecycle..."
TARGET_ID=${INCIDENT_ID_1:-$INCIDENT_ID_2}

if [ -n "$TARGET_ID" ]; then
    devctl incident claim "$TARGET_ID" >/dev/null 2>&1
    CLAIM_STATE=$(devctl incident list | grep "$TARGET_ID" | grep -i "CLAIMED")
    
    devctl incident resolve "$TARGET_ID" --notes 'Fixed by E2E test' >/dev/null 2>&1
    RESOLVE_STATE=$(devctl incident list | grep "$TARGET_ID" | grep -i "RESOLVED")
    
    if [ -n "$CLAIM_STATE" ] && [ -n "$RESOLVE_STATE" ]; then
        record_result "Incident Lifecycle" "PASS" "Successfully claimed and resolved $TARGET_ID"
    else
        record_result "Incident Lifecycle" "FAIL" "Failed to verify CLAIMED/RESOLVED state changes"
    fi
else
    record_result "Incident Lifecycle" "FAIL" "No incident ID available from Test 1 or 2"
fi

# ---------------------------------------------------------
# Test 5: Dashboard API Verification
# ---------------------------------------------------------
echo -e "\nRunning Test 5: Dashboard API Verification..."
API_FAIL=0
API_DETAILS=""

STATUS_RES=$(curl -s http://localhost:8888/api/status || echo "")
if ! echo "$STATUS_RES" | grep -q '"services"'; then
    API_FAIL=1
    API_DETAILS+="Missing 'services' key. "
fi

INCIDENTS_RES=$(curl -s http://localhost:8888/api/incidents || echo "")
if ! echo "$INCIDENTS_RES" | grep -q '"incidents"'; then
    API_FAIL=1
    API_DETAILS+="Missing 'incidents' key. "
fi

NODES_RES=$(curl -s http://localhost:8888/api/fleet/nodes || echo "")
if ! echo "$NODES_RES" | grep -q '"nodes"'; then
    API_FAIL=1
    API_DETAILS+="Missing 'nodes' key. "
fi

if [ $API_FAIL -eq 0 ]; then
    record_result "Dashboard API Verification" "PASS" "All API endpoints returned expected JSON"
else
    record_result "Dashboard API Verification" "FAIL" "$API_DETAILS"
fi

# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------
echo -e "\n================================================================================"
echo "                               TEST SUMMARY                                     "
echo "================================================================================"
printf "%-30s | %-14s | %s\n" "Test Name" "Result" "Details"
echo "-------------------------------+----------------+-------------------------------"
for i in "${!TEST_NAMES[@]}"; do
    printf "%-30s | %b\t| %s\n" "${TEST_NAMES[$i]}" "${TEST_RESULTS[$i]}" "${TEST_DETAILS[$i]}"
done
echo "================================================================================"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}All tests passed successfully!${NC}"
    exit 0
else
    echo -e "${RED}$FAILED_TESTS test(s) failed.${NC}"
    exit 1
fi
