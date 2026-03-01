#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# Deploy ALL hill challenge services
# Usage: ./deploy-all.sh [--skip-pivot]
# ═══════════════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     DEPLOYING ALL HILL CHALLENGE SERVICES                   ║"
echo "║     KoTH CTF Platform                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Hill 1 - Web Fortress (dedicated server)
echo "━━━ Hill 1: Web Fortress ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bash "$SCRIPT_DIR/deploy-hill.sh" 1
echo ""

# Hill 2 - Service Bastion (dedicated server)
echo "━━━ Hill 2: Service Bastion ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bash "$SCRIPT_DIR/deploy-hill.sh" 2
echo ""

if [ "$1" != "--skip-pivot" ]; then
    # Hill 3 - API Gateway (on Pivot DMZ)
    echo "━━━ Hill 3: API Gateway ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bash "$SCRIPT_DIR/deploy-hill.sh" 3
    echo ""

    # Hill 4 - Data Vault (on Pivot DMZ)
    echo "━━━ Hill 4: Data Vault ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bash "$SCRIPT_DIR/deploy-hill.sh" 4
    echo ""
else
    echo "[!] Skipping Hill 3 & 4 (Pivot DMZ) as requested"
fi

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     ALL HILLS DEPLOYED SUCCESSFULLY                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
