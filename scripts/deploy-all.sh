#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Master Deployment Script
# Run from: Local machine / control node
# Deploys everything to all 5 servers
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Server Config ─────────────────────────────────────────────────────
SSH_USER="root"
SSH_PASS="${SSH_PASS:-CHANGE_ME}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"

KOTH_SERVER="${KOTH_SERVER_IP:-YOUR_KOTH_IP}"
HILL1="${HILL1_PUBLIC_IP:-YOUR_HILL1_IP}"
HILL2="${HILL2_PUBLIC_IP:-YOUR_HILL2_IP}"
PIVOT="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
VPN_SERVER="${VPN_SERVER_IP:-YOUR_VPN_IP}"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — Master Deployment"
echo "════════════════════════════════════════════════════════"
echo "  Project: ${PROJECT_DIR}"
echo ""

# Helper function: remote exec
remote_exec() {
    local host=$1
    local cmd=$2
    echo "  [${host}] Running: ${cmd:0:60}..."
    sshpass -p "${SSH_PASS}" ssh ${SSH_OPTS} ${SSH_USER}@${host} "${cmd}"
}

# Helper function: copy file
remote_copy() {
    local host=$1
    local src=$2
    local dst=$3
    echo "  [${host}] Copying: ${src} → ${dst}"
    sshpass -p "${SSH_PASS}" scp ${SSH_OPTS} "${src}" ${SSH_USER}@${host}:"${dst}"
}

# Helper function: copy directory
remote_copy_dir() {
    local host=$1
    local src=$2
    local dst=$3
    echo "  [${host}] Copying dir: ${src} → ${dst}"
    sshpass -p "${SSH_PASS}" scp ${SSH_OPTS} -r "${src}" ${SSH_USER}@${host}:"${dst}"
}

# Check sshpass is available
if ! command -v sshpass &> /dev/null; then
    echo "ERROR: sshpass is required. Install with: apt install sshpass / brew install sshpass"
    exit 1
fi

# ── Phase 1: VPN Server ──────────────────────────────────────────────
echo ""
echo "═══ Phase 1: VPN Server (${VPN_SERVER}) ═══"
remote_copy "${VPN_SERVER}" "${PROJECT_DIR}/scripts/setup-vpn.sh" "/tmp/setup-vpn.sh"
remote_exec "${VPN_SERVER}" "chmod +x /tmp/setup-vpn.sh && /tmp/setup-vpn.sh"
echo "  ✅ VPN Server configured"

# ── Phase 2: Pivot DMZ ───────────────────────────────────────────────
echo ""
echo "═══ Phase 2: Pivot DMZ (${PIVOT}) ═══"
remote_copy "${PIVOT}" "${PROJECT_DIR}/scripts/setup-pivot.sh" "/tmp/setup-pivot.sh"
remote_exec "${PIVOT}" "chmod +x /tmp/setup-pivot.sh && /tmp/setup-pivot.sh"
echo "  ✅ Pivot DMZ configured"

# ── Phase 3: Hill 1 ──────────────────────────────────────────────────
echo ""
echo "═══ Phase 3: Hill 1 - Web (${HILL1}) ═══"
remote_copy "${HILL1}" "${PROJECT_DIR}/scripts/setup-hill1.sh" "/tmp/setup-hill1.sh"
remote_exec "${HILL1}" "chmod +x /tmp/setup-hill1.sh && /tmp/setup-hill1.sh"
echo "  ✅ Hill 1 configured"

# ── Phase 4: Hill 2 ──────────────────────────────────────────────────
echo ""
echo "═══ Phase 4: Hill 2 - Services (${HILL2}) ═══"
remote_copy "${HILL2}" "${PROJECT_DIR}/scripts/setup-hill2.sh" "/tmp/setup-hill2.sh"
remote_exec "${HILL2}" "chmod +x /tmp/setup-hill2.sh && /tmp/setup-hill2.sh"
echo "  ✅ Hill 2 configured"

# ── Phase 5: KoTH Server (Main) ──────────────────────────────────────
echo ""
echo "═══ Phase 5: KoTH Server (${KOTH_SERVER}) ═══"

# 5a. Base setup
remote_copy "${KOTH_SERVER}" "${PROJECT_DIR}/scripts/setup-koth-server.sh" "/tmp/setup-koth-server.sh"
remote_exec "${KOTH_SERVER}" "chmod +x /tmp/setup-koth-server.sh && /tmp/setup-koth-server.sh"

# 5b. Copy project files
echo "  Copying project files..."
remote_exec "${KOTH_SERVER}" "mkdir -p /opt/koth"
remote_copy "${KOTH_SERVER}" "${PROJECT_DIR}/docker-compose.yml" "/opt/koth/docker-compose.yml"
remote_copy "${KOTH_SERVER}" "${PROJECT_DIR}/.env" "/opt/koth/.env"
remote_copy_dir "${KOTH_SERVER}" "${PROJECT_DIR}/scoreboard" "/opt/koth/"
remote_copy_dir "${KOTH_SERVER}" "${PROJECT_DIR}/scorebot" "/opt/koth/"
remote_copy_dir "${KOTH_SERVER}" "${PROJECT_DIR}/nginx" "/opt/koth/"
remote_copy_dir "${KOTH_SERVER}" "${PROJECT_DIR}/prometheus" "/opt/koth/"
remote_copy_dir "${KOTH_SERVER}" "${PROJECT_DIR}/grafana" "/opt/koth/"

# 5c. Build and start
echo "  Building and starting services..."
remote_exec "${KOTH_SERVER}" "cd /opt/koth && docker compose up -d --build"

echo "  ✅ KoTH Server configured and running"

# ── Phase 6: Verification ────────────────────────────────────────────
echo ""
echo "═══ Phase 6: Verification ═══"

echo "  Checking VPN..."
remote_exec "${VPN_SERVER}" "wg show | head -5" || echo "  ⚠ VPN check failed"

echo "  Checking Pivot..."
remote_exec "${PIVOT}" "iptables -t nat -L PREROUTING -n | head -10" || echo "  ⚠ Pivot check failed"

echo "  Checking Hill 1..."
remote_exec "${HILL1}" "docker ps --format 'table {{.Names}}\t{{.Status}}' && cat /root/king.txt" || echo "  ⚠ Hill 1 check failed"

echo "  Checking Hill 2..."
remote_exec "${HILL2}" "docker ps --format 'table {{.Names}}\t{{.Status}}' && cat /root/king.txt" || echo "  ⚠ Hill 2 check failed"

echo "  Checking KoTH Server..."
remote_exec "${KOTH_SERVER}" "docker compose -f /opt/koth/docker-compose.yml ps" || echo "  ⚠ KoTH check failed"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ FULL DEPLOYMENT COMPLETE!"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │ Scoreboard: http://${KOTH_SERVER}           │"
echo "  │ Admin:      http://${KOTH_SERVER}/admin.html│"
echo "  │ Grafana:    http://${KOTH_SERVER}/grafana   │"
echo "  │ API:        http://${KOTH_SERVER}/api/health│"
echo "  └─────────────────────────────────────────────┘"
echo ""
echo "  VPN configs: ssh root@${VPN_SERVER} ls /etc/wireguard/clients/"
echo ""
echo "  Next: Register teams via Admin panel or API"
echo "════════════════════════════════════════════════════════"
