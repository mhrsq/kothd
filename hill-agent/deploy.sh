#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# KoTH CTF — Hill Agent Deployment Script
# Deploy the hill agent to a remote hill server.
#
# Usage:
#   ./deploy.sh <hill_ip> <hill_id> <agent_token> [options]
#
# Example:
#   ./deploy.sh 10.0.1.2 1 "agent-hill-1-abc123def456"
#   ./deploy.sh 10.0.1.3 2 "agent-hill-2-abc123def456" --sla-port=80 --sla-type=http
#
# Prerequisites:
#   - Go 1.22+ installed locally OR the pre-built binary
#   - SSH access to the hill server (root)
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

KOTH_SERVER="${KOTH_SERVER:-http://YOUR_KOTH_SERVER:8000}"
REPORT_INTERVAL="${REPORT_INTERVAL:-10}"
SSH_USER="${SSH_USER:-root}"
SSH_PASS="${SSH_PASS:-}"
KING_FILE="${KING_FILE:-/root/king.txt}"

# Parse args
HILL_IP="${1:-}"
HILL_ID="${2:-}"
AGENT_TOKEN="${3:-}"
SLA_PORT="${SLA_PORT:-0}"
SLA_TYPE="${SLA_TYPE:-}"

# Parse optional flags
shift 3 2>/dev/null || true
for arg in "$@"; do
    case $arg in
        --sla-port=*) SLA_PORT="${arg#*=}" ;;
        --sla-type=*) SLA_TYPE="${arg#*=}" ;;
        --interval=*) REPORT_INTERVAL="${arg#*=}" ;;
        --server=*)   KOTH_SERVER="${arg#*=}" ;;
        --king-file=*) KING_FILE="${arg#*=}" ;;
    esac
done

if [[ -z "$HILL_IP" || -z "$HILL_ID" || -z "$AGENT_TOKEN" ]]; then
    echo "Usage: $0 <hill_ip> <hill_id> <agent_token> [--sla-port=80] [--sla-type=http]"
    exit 1
fi

echo "═══════════════════════════════════════════════════"
echo "  KoTH CTF — Hill Agent Deployer"
echo "  Target: ${SSH_USER}@${HILL_IP}"
echo "  Hill ID: ${HILL_ID}"
echo "  KoTH Server: ${KOTH_SERVER}"
echo "  Interval: ${REPORT_INTERVAL}s"
echo "═══════════════════════════════════════════════════"

# Build the agent binary for Linux amd64
echo "[1/4] Building hill-agent binary..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o hill-agent-linux .
echo "  ✓ Built hill-agent-linux ($(du -h hill-agent-linux | cut -f1))"

# Upload binary to hill
echo "[2/4] Uploading binary to ${HILL_IP}..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${HILL_IP}" "mkdir -p /opt/koth"
sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no hill-agent-linux "${SSH_USER}@${HILL_IP}:/opt/koth/hill-agent"
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${HILL_IP}" "chmod +x /opt/koth/hill-agent"
echo "  ✓ Binary uploaded"

# Create systemd service
echo "[3/4] Installing systemd service..."
SERVICE_CONTENT="[Unit]
Description=KoTH CTF - Hill Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/koth/hill-agent
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=koth-agent

Environment=\"HILL_ID=${HILL_ID}\"
Environment=\"AGENT_TOKEN=${AGENT_TOKEN}\"
Environment=\"KOTH_SERVER=${KOTH_SERVER}\"
Environment=\"REPORT_INTERVAL=${REPORT_INTERVAL}\"
Environment=\"KING_FILE=${KING_FILE}\"
Environment=\"SLA_CHECK_PORT=${SLA_PORT}\"
Environment=\"SLA_CHECK_TYPE=${SLA_TYPE}\"

[Install]
WantedBy=multi-user.target"

sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${HILL_IP}" "cat > /etc/systemd/system/koth-agent.service << 'SERVICEEOF'
${SERVICE_CONTENT}
SERVICEEOF"

# Enable and start
echo "[4/4] Starting agent service..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "${SSH_USER}@${HILL_IP}" \
    "systemctl daemon-reload && systemctl enable koth-agent && systemctl restart koth-agent && sleep 1 && systemctl status koth-agent --no-pager"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ Hill Agent deployed to ${HILL_IP}"
echo "  Hill ID: ${HILL_ID}"
echo "  Service: koth-agent.service"
echo "  Logs: journalctl -u koth-agent -f"
echo "═══════════════════════════════════════════════════"

# Cleanup
rm -f hill-agent-linux
