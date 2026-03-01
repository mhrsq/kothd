#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Deployment Verification Script
# Run from: Local machine / control node
# Checks all services across all servers
# ═══════════════════════════════════════════════════════════════════════

set -uo pipefail

SSH_USER="root"
SSH_PASS="${SSH_PASS:-CHANGE_ME}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"

KOTH_SERVER="${KOTH_SERVER_IP:-YOUR_KOTH_IP}"
HILL1="${HILL1_PUBLIC_IP:-YOUR_HILL1_IP}"
HILL2="${HILL2_PUBLIC_IP:-YOUR_HILL2_IP}"
PIVOT="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
VPN_SERVER="${VPN_SERVER_IP:-YOUR_VPN_IP}"

PASS=0
FAIL=0

check() {
    local desc=$1
    local cmd=$2
    if eval "${cmd}" > /dev/null 2>&1; then
        echo "  ✅ ${desc}"
        ((PASS++))
    else
        echo "  ❌ ${desc}"
        ((FAIL++))
    fi
}

remote() {
    sshpass -p "${SSH_PASS}" ssh ${SSH_OPTS} ${SSH_USER}@$1 "$2" 2>/dev/null
}

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — Deployment Verification"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════"

# ── SSH Connectivity ──────────────────────────────────────────────────
echo ""
echo "── SSH Connectivity ──"
check "KoTH Server SSH"  "remote ${KOTH_SERVER} 'echo ok'"
check "Hill 1 SSH"       "remote ${HILL1} 'echo ok'"
check "Hill 2 SSH"       "remote ${HILL2} 'echo ok'"
check "Pivot DMZ SSH"    "remote ${PIVOT} 'echo ok'"
check "VPN Server SSH"   "remote ${VPN_SERVER} 'echo ok'"

# ── VPN Server ────────────────────────────────────────────────────────
echo ""
echo "── VPN Server (${VPN_SERVER}) ──"
check "WireGuard running"    "remote ${VPN_SERVER} 'wg show wg0'"
check "Team configs exist"   "remote ${VPN_SERVER} 'ls /etc/wireguard/clients/team-01.conf'"
check "IP forwarding"        "remote ${VPN_SERVER} 'sysctl net.ipv4.ip_forward | grep 1'"

# ── Pivot DMZ ─────────────────────────────────────────────────────────
echo ""
echo "── Pivot DMZ (${PIVOT}) ──"
check "IP forwarding"        "remote ${PIVOT} 'sysctl net.ipv4.ip_forward | grep 1'"
check "NAT rules present"    "remote ${PIVOT} 'iptables -t nat -L PREROUTING -n | grep DNAT'"
check "Docker running"       "remote ${PIVOT} 'docker ps | grep pivot'"

# ── Hill 1 (Web) ─────────────────────────────────────────────────────
echo ""
echo "── Hill 1 Web (${HILL1}) ──"
check "king.txt exists"      "remote ${HILL1} 'cat /root/king.txt'"
check "Docker containers"    "remote ${HILL1} 'docker ps | grep hill1'"
check "Web app (port 80)"    "curl -s --connect-timeout 5 http://${HILL1}:80/ | grep -qi 'vulncorp\|html'"
check "API (port 3000)"      "curl -s --connect-timeout 5 http://${HILL1}:3000/api/health | grep -q 'ok'"

# ── Hill 2 (Services) ────────────────────────────────────────────────
echo ""
echo "── Hill 2 Services (${HILL2}) ──"
check "king.txt exists"      "remote ${HILL2} 'cat /root/king.txt'"
check "Docker containers"    "remote ${HILL2} 'docker ps | grep hill2'"
check "Dashboard (port 80)"  "curl -s --connect-timeout 5 http://${HILL2}:80/health | grep -q 'ok'"
check "Redis (port 6379)"    "remote ${HILL2} 'docker exec hill2-vuln-redis redis-cli ping' | grep -q 'PONG'"

# ── KoTH Server ──────────────────────────────────────────────────────
echo ""
echo "── KoTH Server (${KOTH_SERVER}) ──"
check "Docker Compose up"    "remote ${KOTH_SERVER} 'cd /opt/koth && docker compose ps | grep running'"
check "Scoreboard API"       "curl -s --connect-timeout 5 http://${KOTH_SERVER}/api/health | grep -q 'ok'"
check "Scoreboard UI"        "curl -s --connect-timeout 5 http://${KOTH_SERVER}/ | grep -qi 'koth\|scoreboard'"
check "Grafana"              "curl -s --connect-timeout 5 http://${KOTH_SERVER}/grafana/api/health | grep -q 'ok'"
check "PostgreSQL"           "remote ${KOTH_SERVER} 'docker exec koth-db pg_isready' | grep -q 'accepting'"
check "Redis"                "remote ${KOTH_SERVER} 'docker exec koth-redis redis-cli ping' | grep -q 'PONG'"

# ── Network Connectivity (Internal) ──────────────────────────────────
echo ""
echo "── Internal Network ──"
check "KoTH→Hill1 (${HILL1_VPC_IP:-10.x.x.2})"  "remote ${KOTH_SERVER} 'ping -c1 -W2 ${HILL1_VPC_IP:-10.x.x.2}'"
check "KoTH→Hill2 (${HILL2_VPC_IP:-10.x.x.3})"  "remote ${KOTH_SERVER} 'ping -c1 -W2 ${HILL2_VPC_IP:-10.x.x.3}'"
check "KoTH→Pivot (${PIVOT_VPC_IP:-10.x.x.4})"  "remote ${KOTH_SERVER} 'ping -c1 -W2 ${PIVOT_VPC_IP:-10.x.x.4}'"
check "KoTH→VPN (${VPN_VPC_IP:-10.x.x.5})"    "remote ${KOTH_SERVER} 'ping -c1 -W2 ${VPN_VPC_IP:-10.x.x.5}'"

# ── Summary ───────────────────────────────────────────────────────────
TOTAL=$((PASS + FAIL))
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Verification Results: ${PASS}/${TOTAL} passed"
if [ ${FAIL} -eq 0 ]; then
    echo "  ✅ ALL CHECKS PASSED — Ready for competition!"
else
    echo "  ⚠ ${FAIL} checks failed — review above"
fi
echo "════════════════════════════════════════════════════════"
