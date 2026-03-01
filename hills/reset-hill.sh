#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# Reset a hill challenge to initial state
# Rebuilds the container, restoring king.txt and all data
# Usage: ./reset-hill.sh <hill_number>
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
        TARGET_IP="${HILL1_PUBLIC_IP:-YOUR_HILL1_IP}"
        REMOTE_DIR="/opt/hill/challenge"
        CONTAINER="hill1-web-fortress"
        HILL_NAME="Web Fortress"
        ;;
    2)
        TARGET_IP="${HILL2_PUBLIC_IP:-YOUR_HILL2_IP}"
        REMOTE_DIR="/opt/hill/challenge"
        CONTAINER="hill2-service-bastion"
        HILL_NAME="Service Bastion"
        ;;
    3)
        TARGET_IP="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
        REMOTE_DIR="/opt/hill/hill3"
        CONTAINER="hill3-api-gateway"
        HILL_NAME="API Gateway"
        ;;
    4)
        TARGET_IP="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
        REMOTE_DIR="/opt/hill/hill4"
        CONTAINER="hill4-data-vault"
        HILL_NAME="Data Vault"
        ;;
    *)
        echo "Invalid hill number. Use 1-4."
        exit 1
        ;;
esac

echo "═══════════════════════════════════════════════════════════════"
echo "  Resetting Hill $HILL_NUM: $HILL_NAME"
echo "  Target: root@$TARGET_IP"
echo "═══════════════════════════════════════════════════════════════"

SSH_CMD="sshpass -p '$SSH_PASS' ssh -o StrictHostKeyChecking=no root@$TARGET_IP"

echo "[1/4] Stopping container..."
eval $SSH_CMD "cd $REMOTE_DIR && docker compose down -v 2>/dev/null || true"

echo "[2/4] Pruning old images..."
eval $SSH_CMD "docker image prune -f 2>/dev/null || true"

echo "[3/4] Rebuilding and starting..."
eval $SSH_CMD "cd $REMOTE_DIR && docker compose build --no-cache && docker compose up -d"

echo "[4/4] Verifying..."
sleep 3
eval $SSH_CMD "cd $REMOTE_DIR && docker compose ps"
echo ""
eval $SSH_CMD "docker exec $CONTAINER cat /root/king.txt 2>/dev/null && echo '' || echo 'Waiting for container...'"

echo ""
echo "[✓] Hill $HILL_NUM ($HILL_NAME) reset to initial state!"
