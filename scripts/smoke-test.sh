#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Smoke Test / Health Check
# Validates all services are running and responding correctly.
#
# Usage:
#   ./scripts/smoke-test.sh              # run all checks
#   ./scripts/smoke-test.sh --quick      # skip slow checks
#
# Exit codes: 0 = all passed, 1 = failures detected
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0
QUICK=false
[[ "${1:-}" == "--quick" ]] && QUICK=true

check_pass() { echo -e "  ${GREEN}✓${NC} $*"; PASS=$((PASS+1)); }
check_fail() { echo -e "  ${RED}✗${NC} $*"; FAIL=$((FAIL+1)); }
check_warn() { echo -e "  ${YELLOW}!${NC} $*"; WARN=$((WARN+1)); }

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  KoTH CTF — Smoke Test"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# ── 1. Docker Compose status ─────────────────────────────────────────
echo "▸ Docker Containers"
EXPECTED_SERVICES=("db" "redis" "scoreboard" "scorebot" "nginx")
for svc in "${EXPECTED_SERVICES[@]}"; do
    STATUS=$(docker compose ps --format '{{.State}}' "$svc" 2>/dev/null || echo "missing")
    if [[ "$STATUS" == "running" ]]; then
        check_pass "$svc is running"
    else
        check_fail "$svc — state: ${STATUS}"
    fi
done
echo ""

# ── 2. Port checks ───────────────────────────────────────────────────
echo "▸ Port Connectivity"
declare -A PORTS=( ["80"]="Nginx HTTP" ["8000"]="Scoreboard API" )
for port in "${!PORTS[@]}"; do
    if curl -sf --max-time 5 "http://localhost:${port}/" &>/dev/null || \
       curl -sf --max-time 5 "http://localhost:${port}/api/health" &>/dev/null; then
        check_pass "${PORTS[$port]} (:${port}) responding"
    else
        check_fail "${PORTS[$port]} (:${port}) not responding"
    fi
done
echo ""

# ── 3. API Health endpoint ───────────────────────────────────────────
echo "▸ API Health"
HEALTH=$(curl -sf --max-time 5 http://localhost:8000/api/health 2>/dev/null || echo '{}')
if echo "$HEALTH" | grep -q '"version"'; then
    VERSION=$(echo "$HEALTH" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
    STATUS=$(echo "$HEALTH" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    check_pass "API version: ${VERSION}, status: ${STATUS}"
else
    check_fail "API health endpoint not returning valid JSON"
fi

# Check via nginx proxy
HEALTH_NGINX=$(curl -sf --max-time 5 http://localhost/api/health 2>/dev/null || echo '{}')
if echo "$HEALTH_NGINX" | grep -q '"version"'; then
    check_pass "Nginx proxy → API health OK"
else
    check_fail "Nginx proxy → API health failed"
fi
echo ""

# ── 4. Database connectivity ─────────────────────────────────────────
echo "▸ Database"
DB_CHECK=$(docker compose exec -T db pg_isready -U koth -d kothdb 2>/dev/null || echo "failed")
if echo "$DB_CHECK" | grep -q "accepting connections"; then
    check_pass "PostgreSQL accepting connections"
else
    check_fail "PostgreSQL not ready: ${DB_CHECK}"
fi

# Check tables exist
TABLE_COUNT=$(docker compose exec -T db psql -U koth -d kothdb -t -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ' || echo "0")
if [[ "$TABLE_COUNT" -ge 5 ]]; then
    check_pass "Database has ${TABLE_COUNT} tables"
else
    check_fail "Expected ≥5 tables, found: ${TABLE_COUNT}"
fi
echo ""

# ── 5. Redis connectivity ────────────────────────────────────────────
echo "▸ Redis"
REDIS_PONG=$(docker compose exec -T redis redis-cli ping 2>/dev/null || echo "failed")
if [[ "$REDIS_PONG" == *"PONG"* ]]; then
    check_pass "Redis responding to PING"
else
    check_fail "Redis not responding: ${REDIS_PONG}"
fi
echo ""

# ── 6. .env security ─────────────────────────────────────────────────
echo "▸ Configuration"
if [[ -f .env ]]; then
    check_pass ".env file exists"
    PERMS=$(stat -c '%a' .env 2>/dev/null || stat -f '%Lp' .env 2>/dev/null || echo "unknown")
    if [[ "$PERMS" == "600" ]]; then
        check_pass ".env permissions: 600"
    else
        check_warn ".env permissions: ${PERMS} (recommended: 600)"
    fi
    # Check for default passwords
    if grep -q 'CHANGE_ME\|changeme\|password123' .env 2>/dev/null; then
        check_fail ".env contains default passwords — run: bash scripts/generate-env.sh"
    else
        check_pass ".env has no default passwords"
    fi
else
    check_fail ".env file missing — run: bash scripts/generate-env.sh"
fi
echo ""

# ── 7. API endpoints (if not --quick) ────────────────────────────────
if ! $QUICK; then
    echo "▸ API Endpoints"

    # Game status
    GAME=$(curl -sf --max-time 5 http://localhost:8000/api/game/status 2>/dev/null || echo "failed")
    if [[ "$GAME" != "failed" ]]; then
        check_pass "GET /api/game/status responds"
    else
        check_fail "GET /api/game/status failed"
    fi

    # Scoreboard
    SCORES=$(curl -sf --max-time 5 http://localhost:8000/api/scoreboard 2>/dev/null || echo "failed")
    if [[ "$SCORES" != "failed" ]]; then
        check_pass "GET /api/scoreboard responds"
    else
        check_fail "GET /api/scoreboard failed"
    fi

    # Hills
    HILLS=$(curl -sf --max-time 5 http://localhost:8000/api/hills 2>/dev/null || echo "failed")
    if [[ "$HILLS" != "failed" ]]; then
        check_pass "GET /api/hills responds"
    else
        check_fail "GET /api/hills failed"
    fi

    # Auth endpoint (should reject without creds)
    AUTH_STATUS=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 \
        http://localhost:8000/api/auth/login 2>/dev/null || echo "000")
    if [[ "$AUTH_STATUS" =~ ^(405|422|400|401)$ ]]; then
        check_pass "POST /api/auth/login rejects unauthenticated (HTTP ${AUTH_STATUS})"
    elif [[ "$AUTH_STATUS" == "000" ]]; then
        check_fail "POST /api/auth/login not reachable"
    else
        check_warn "POST /api/auth/login returned HTTP ${AUTH_STATUS}"
    fi
    echo ""
fi

# ── 8. Resource usage ────────────────────────────────────────────────
if ! $QUICK; then
    echo "▸ Resource Usage"
    docker compose ps --format '{{.Name}}\t{{.Status}}' 2>/dev/null | while IFS=$'\t' read -r name status; do
        echo -e "    ${name}: ${status}"
    done
    echo ""

    # Disk usage
    DISK_USAGE=$(docker system df --format '{{.Type}}\t{{.Size}}' 2>/dev/null | head -5)
    if [[ -n "$DISK_USAGE" ]]; then
        echo "  Docker disk usage:"
        echo "$DISK_USAGE" | while IFS=$'\t' read -r type size; do
            echo "    ${type}: ${size}"
        done
    fi
    echo ""
fi

# ── Summary ───────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════════"
echo -e "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}, ${YELLOW}${WARN} warnings${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo -e "  ${RED}Some checks failed.${NC} Review output above."
    echo "  Logs: docker compose logs [service]"
    exit 1
else
    echo -e "  ${GREEN}All checks passed!${NC}"
    exit 0
fi
