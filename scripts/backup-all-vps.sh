#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Full VPS Backup Script
# Backs up ALL server data for on-premise migration
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

BACKUP_DIR="/tmp/koth-backup-$(date +%Y%m%d-%H%M%S)"
PASS="${SSH_PASS:-CHANGE_ME}"

KOTH_IP="${KOTH_SERVER_IP:-YOUR_KOTH_IP}"
HILL1_IP="${HILL1_PUBLIC_IP:-YOUR_HILL1_IP}"
HILL2_IP="${HILL2_PUBLIC_IP:-YOUR_HILL2_IP}"
PIVOT_IP="${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP}"
VPN_IP="${VPN_SERVER_IP:-YOUR_VPN_IP}"

SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no"
SCP="sshpass -p $PASS scp -o StrictHostKeyChecking=no -r"

mkdir -p "$BACKUP_DIR"/{koth,hill1,hill2,pivot,vpn}

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — Full VPS Backup"
echo "  Output: $BACKUP_DIR"
echo "════════════════════════════════════════════════════════"

# ═══════════════════════════════════════════════════════════════
# 1. KoTH Main Server (${KOTH_SERVER_IP:-YOUR_KOTH_IP})
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[1/5] Backing up KoTH Main Server..."

# PostgreSQL full dump
echo "  → PostgreSQL dump..."
$SSH root@$KOTH_IP "docker exec koth-db pg_dump -U koth_admin -d koth --format=custom -f /tmp/koth_db.dump && docker cp koth-db:/tmp/koth_db.dump /tmp/koth_db.dump"
$SCP root@$KOTH_IP:/tmp/koth_db.dump "$BACKUP_DIR/koth/"

# Also SQL format for readability
$SSH root@$KOTH_IP "docker exec koth-db pg_dump -U koth_admin -d koth > /tmp/koth_db.sql"
$SCP root@$KOTH_IP:/tmp/koth_db.sql "$BACKUP_DIR/koth/"

# Redis dump
echo "  → Redis dump..."
$SSH root@$KOTH_IP "docker exec koth-redis redis-cli -a ${REDIS_PASSWORD:-CHANGE_ME} BGSAVE && sleep 2 && docker cp koth-redis:/data/dump.rdb /tmp/redis_dump.rdb"
$SCP root@$KOTH_IP:/tmp/redis_dump.rdb "$BACKUP_DIR/koth/"

# Scorebot SSH keys
echo "  → Scorebot keys..."
$SSH root@$KOTH_IP "docker cp koth-scorebot:/app/keys /tmp/scorebot_keys 2>/dev/null || echo 'no keys dir'"
$SCP root@$KOTH_IP:/tmp/scorebot_keys "$BACKUP_DIR/koth/" 2>/dev/null || echo "  (no scorebot keys to backup)"

# Full /opt/koth project
echo "  → Project files..."
$SSH root@$KOTH_IP "cd /opt && tar czf /tmp/koth-project.tar.gz --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' koth/"
$SCP root@$KOTH_IP:/tmp/koth-project.tar.gz "$BACKUP_DIR/koth/"

# Docker volume data (grafana dashboards, prometheus)
echo "  → Grafana provisioning..."
$SSH root@$KOTH_IP "docker cp koth-grafana:/var/lib/grafana /tmp/grafana_data 2>/dev/null && tar czf /tmp/grafana_data.tar.gz -C /tmp grafana_data"
$SCP root@$KOTH_IP:/tmp/grafana_data.tar.gz "$BACKUP_DIR/koth/" 2>/dev/null || echo "  (grafana data skipped)"

# Docker images list
$SSH root@$KOTH_IP "docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}'" > "$BACKUP_DIR/koth/docker-images.txt"

# Environment info
$SSH root@$KOTH_IP "cat /opt/koth/.env" > "$BACKUP_DIR/koth/env-backup.txt"
$SSH root@$KOTH_IP "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'" > "$BACKUP_DIR/koth/docker-ps.txt"
$SSH root@$KOTH_IP "ip addr show" > "$BACKUP_DIR/koth/network-config.txt"
$SSH root@$KOTH_IP "cat /etc/netplan/*.yaml 2>/dev/null" > "$BACKUP_DIR/koth/netplan.txt" 2>/dev/null || true
$SSH root@$KOTH_IP "iptables -L -n -v 2>/dev/null; echo '---NAT---'; iptables -t nat -L -n -v 2>/dev/null" > "$BACKUP_DIR/koth/iptables.txt"

echo "  ✓ KoTH backup complete"

# ═══════════════════════════════════════════════════════════════
# 2. Hill 1 — Web Fortress (${HILL1_PUBLIC_IP:-YOUR_HILL1_IP})
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[2/5] Backing up Hill 1..."

$SSH root@$HILL1_IP "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'" > "$BACKUP_DIR/hill1/docker-ps.txt"
$SSH root@$HILL1_IP "ip addr show" > "$BACKUP_DIR/hill1/network-config.txt"

# Export hill container image
echo "  → Exporting container image..."
$SSH root@$HILL1_IP "docker save hill-challenge-web-fortress | gzip > /tmp/hill1-image.tar.gz"
$SCP root@$HILL1_IP:/tmp/hill1-image.tar.gz "$BACKUP_DIR/hill1/"

# Backup challenge files if deployed from source
$SSH root@$HILL1_IP "if [ -d /opt/hill-challenge ]; then tar czf /tmp/hill1-src.tar.gz -C /opt hill-challenge; fi"
$SCP root@$HILL1_IP:/tmp/hill1-src.tar.gz "$BACKUP_DIR/hill1/" 2>/dev/null || echo "  (no source dir)"

echo "  ✓ Hill 1 backup complete"

# ═══════════════════════════════════════════════════════════════
# 3. Hill 2 — Service Bastion (${HILL2_PUBLIC_IP:-YOUR_HILL2_IP})
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[3/5] Backing up Hill 2..."

$SSH root@$HILL2_IP "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'" > "$BACKUP_DIR/hill2/docker-ps.txt"
$SSH root@$HILL2_IP "ip addr show" > "$BACKUP_DIR/hill2/network-config.txt"

echo "  → Exporting container image..."
$SSH root@$HILL2_IP "docker save hill-challenge-service-bastion | gzip > /tmp/hill2-image.tar.gz"
$SCP root@$HILL2_IP:/tmp/hill2-image.tar.gz "$BACKUP_DIR/hill2/"

$SSH root@$HILL2_IP "if [ -d /opt/hill-challenge ]; then tar czf /tmp/hill2-src.tar.gz -C /opt hill-challenge; fi"
$SCP root@$HILL2_IP:/tmp/hill2-src.tar.gz "$BACKUP_DIR/hill2/" 2>/dev/null || echo "  (no source dir)"

echo "  ✓ Hill 2 backup complete"

# ═══════════════════════════════════════════════════════════════
# 4. Pivot DMZ — Hill 3 + Hill 4 (${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP})
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[4/5] Backing up Pivot DMZ..."

$SSH root@$PIVOT_IP "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'" > "$BACKUP_DIR/pivot/docker-ps.txt"
$SSH root@$PIVOT_IP "ip addr show" > "$BACKUP_DIR/pivot/network-config.txt"
$SSH root@$PIVOT_IP "cat /etc/netplan/*.yaml 2>/dev/null" > "$BACKUP_DIR/pivot/netplan.txt" 2>/dev/null || true

echo "  → Exporting Hill 3 image..."
$SSH root@$PIVOT_IP "docker save hill-challenge-hill3-api | gzip > /tmp/hill3-image.tar.gz"
$SCP root@$PIVOT_IP:/tmp/hill3-image.tar.gz "$BACKUP_DIR/pivot/"

echo "  → Exporting Hill 4 image..."
$SSH root@$PIVOT_IP "docker save hill-challenge-hill4-db | gzip > /tmp/hill4-image.tar.gz"
$SCP root@$PIVOT_IP:/tmp/hill4-image.tar.gz "$BACKUP_DIR/pivot/"

$SSH root@$PIVOT_IP "if [ -d /opt/hill-challenge ]; then tar czf /tmp/pivot-src.tar.gz -C /opt hill-challenge; fi"
$SCP root@$PIVOT_IP:/tmp/pivot-src.tar.gz "$BACKUP_DIR/pivot/" 2>/dev/null || echo "  (no source dir)"

echo "  ✓ Pivot DMZ backup complete"

# ═══════════════════════════════════════════════════════════════
# 5. VPN Server (${VPN_SERVER_IP:-YOUR_VPN_IP})
# ═══════════════════════════════════════════════════════════════
echo ""
echo "[5/5] Backing up VPN Server..."

# WireGuard config + keys
echo "  → WireGuard configs & keys..."
$SSH root@$VPN_IP "tar czf /tmp/wireguard-full.tar.gz /etc/wireguard/"
$SCP root@$VPN_IP:/tmp/wireguard-full.tar.gz "$BACKUP_DIR/vpn/"

$SSH root@$VPN_IP "ip addr show" > "$BACKUP_DIR/vpn/network-config.txt"
$SSH root@$VPN_IP "ip route" > "$BACKUP_DIR/vpn/routes.txt"
$SSH root@$VPN_IP "iptables -L -n -v; echo '---NAT---'; iptables -t nat -L -n -v; echo '---FORWARD---'; iptables -L FORWARD -n -v" > "$BACKUP_DIR/vpn/iptables.txt"
$SSH root@$VPN_IP "wg show" > "$BACKUP_DIR/vpn/wg-show.txt" 2>/dev/null || true
$SSH root@$VPN_IP "cat /etc/sysctl.conf | grep -v '^#' | grep -v '^$'" > "$BACKUP_DIR/vpn/sysctl.txt" 2>/dev/null || true

echo "  ✓ VPN backup complete"

# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Backup Complete!"
echo "  Location: $BACKUP_DIR"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Contents:"
find "$BACKUP_DIR" -type f -exec ls -lh {} \; | awk '{print $5, $9}'
echo ""
TOTAL=$(du -sh "$BACKUP_DIR" | awk '{print $1}')
echo "Total size: $TOTAL"
echo ""
echo "To create a single archive:"
echo "  tar czf koth-full-backup.tar.gz -C $(dirname $BACKUP_DIR) $(basename $BACKUP_DIR)"
