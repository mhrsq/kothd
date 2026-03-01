#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# Deploy a hill challenge service to its target server
# Usage: ./deploy-hill.sh <hill_number>
# ═══════════════════════════════════════════════════════════════════
set -e

HILL_NUM="$1"
SSH_PASS="${SSH_PASS:-CHANGE_ME}"

if [ -z "$HILL_NUM" ]; then
    echo "Usage: $0 <hill_number> (1-4)"
    exit 1
fi

case "$HILL_NUM" in
    1)
        HILL_DIR="hill1-web"
        TARGET_IP="${HILL1_PUBLIC_IP:-YOUR_HILL1_IP}"
        REMOTE_DIR="/opt/hill/challenge"
        HILL_NAME="Web Fortress"
        ;;
    2)
        HILL_DIR="hill2-services"
        TARGET_IP="${HILL2_PUBLIC_IP:-YOUR_HILL2_IP}"
        REMOTE_DIR="/opt/hill/challenge"
        HILL_NAME="Service Bastion"
        ;;
    3)
        HILL_DIR="hill3-api"
        TARGET_IP="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
        REMOTE_DIR="/opt/hill/hill3"
        HILL_NAME="API Gateway"
        ;;
    4)
        HILL_DIR="hill4-db"
        TARGET_IP="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
        REMOTE_DIR="/opt/hill/hill4"
        HILL_NAME="Data Vault"
        ;;
    *)
        echo "Invalid hill number. Use 1-4."
        exit 1
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/$HILL_DIR"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "[-] Source directory not found: $SOURCE_DIR"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  Deploying Hill $HILL_NUM: $HILL_NAME"
echo "  Source:  $SOURCE_DIR"
echo "  Target:  root@$TARGET_IP:$REMOTE_DIR"
echo "═══════════════════════════════════════════════════════════════"

# Check if sshpass is available
if ! command -v sshpass &> /dev/null; then
    echo "[*] sshpass not found, attempting install..."
    apt-get update -qq && apt-get install -y -qq sshpass
fi

SSH_CMD="sshpass -p '$SSH_PASS' ssh -o StrictHostKeyChecking=no root@$TARGET_IP"
SCP_CMD="sshpass -p '$SSH_PASS' scp -o StrictHostKeyChecking=no -r"
RSYNC_CMD="sshpass -p '$SSH_PASS' rsync -avz --delete -e 'ssh -o StrictHostKeyChecking=no'"

echo "[1/5] Creating remote directory..."
eval $SSH_CMD "mkdir -p $REMOTE_DIR"

echo "[2/5] Syncing challenge files..."
eval $RSYNC_CMD "$SOURCE_DIR/" "root@$TARGET_IP:$REMOTE_DIR/"

echo "[3/5] Setting permissions..."
eval $SSH_CMD "chmod +x $REMOTE_DIR/entrypoint.sh 2>/dev/null || true"

echo "[4/5] Stopping existing containers..."
eval $SSH_CMD "cd $REMOTE_DIR && docker compose down 2>/dev/null || true"

echo "[5/5] Building and starting challenge..."
eval $SSH_CMD "cd $REMOTE_DIR && docker compose build --no-cache && docker compose up -d"

echo ""
echo "[✓] Hill $HILL_NUM ($HILL_NAME) deployed successfully!"
echo ""

# Verify
echo "[*] Verifying deployment..."
eval $SSH_CMD "cd $REMOTE_DIR && docker compose ps"
echo ""
eval $SSH_CMD "docker exec \$(docker compose -f $REMOTE_DIR/docker-compose.yml ps -q | head -1) cat /root/king.txt 2>/dev/null || echo 'king.txt check: container may still be starting'"
