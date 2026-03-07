#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Full VPS Backup Script
# Backs up ALL server data for migration to another VM
# ═══════════════════════════════════════════════════════════════════════
#
# Usage:
#   SSH_PASS="yourpass" REDIS_PASS="yourredispass" ./backup-all-vps.sh
#
# Or edit the defaults below.
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
PASS="${SSH_PASS:-anonyM404.a}"
REDIS_PASS="${REDIS_PASS:-Vaek8KOp2P5j8xMT55Vh49pB}"
PG_USER="${PG_USER:-koth_admin}"
PG_DB="${PG_DB:-koth}"

# Server IPs
KOTH_IP="${KOTH_IP:-178.128.222.1}"
HILL1_IP="${HILL1_IP:-165.22.149.130}"
HILL2_IP="${HILL2_IP:-165.227.10.119}"
HILL3_IP="${HILL3_IP:-165.227.16.235}"
HILL4_IP="${HILL4_IP:-129.212.235.51}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-./koth-backup-${TIMESTAMP}}"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ServerAliveInterval=30"
SSH="sshpass -p ${PASS} ssh ${SSH_OPTS}"
SCP="sshpass -p ${PASS} scp ${SSH_OPTS} -r"

# ── Helpers ───────────────────────────────────────────────────────────
log()  { echo -e "\033[1;36m[$(date +%H:%M:%S)]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓\033[0m $*"; }
warn() { echo -e "\033[1;33m  ⚠\033[0m $*"; }
fail() { echo -e "\033[1;31m  ✗\033[0m $*"; }

# ── Pre-flight ────────────────────────────────────────────────────────
command -v sshpass >/dev/null || { fail "sshpass not installed. apt install sshpass"; exit 1; }

mkdir -p "${BACKUP_DIR}"/{koth,hill1,hill2,hill3,hill4}

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  KoTH CTF — Full VPS Backup"
echo "  Timestamp: ${TIMESTAMP}"
echo "  Output:    ${BACKUP_DIR}"
echo "════════════════════════════════════════════════════════════════"

# ═══════════════════════════════════════════════════════════════════════
# 1. KoTH Main Server
# ═══════════════════════════════════════════════════════════════════════
echo ""
log "[1/5] Backing up KoTH Main Server (${KOTH_IP})..."
CDIR="${BACKUP_DIR}/koth"

log "  → PostgreSQL dump (custom format)..."
$SSH root@${KOTH_IP} "docker exec koth-db pg_dump -U ${PG_USER} -d ${PG_DB} --format=custom -f /tmp/koth_db.dump && docker cp koth-db:/tmp/koth_db.dump /tmp/koth_db.dump" && \
    $SCP root@${KOTH_IP}:/tmp/koth_db.dump "${CDIR}/" && ok "PG dump (custom)" || warn "PG custom dump failed"

log "  → PostgreSQL dump (SQL)..."
$SSH root@${KOTH_IP} "docker exec koth-db pg_dump -U ${PG_USER} -d ${PG_DB} > /tmp/koth_db.sql" && \
    $SCP root@${KOTH_IP}:/tmp/koth_db.sql "${CDIR}/" && ok "PG dump (SQL)" || warn "PG SQL dump failed"

log "  → Redis snapshot..."
$SSH root@${KOTH_IP} "docker exec koth-redis redis-cli -a '${REDIS_PASS}' BGSAVE 2>/dev/null && sleep 2 && docker cp koth-redis:/data/dump.rdb /tmp/redis_dump.rdb" && \
    $SCP root@${KOTH_IP}:/tmp/redis_dump.rdb "${CDIR}/" && ok "Redis dump" || warn "Redis dump failed"

log "  → Redis AOF..."
$SSH root@${KOTH_IP} "docker cp koth-redis:/data/appendonlydir /tmp/redis_aof 2>/dev/null && tar czf /tmp/redis_aof.tar.gz -C /tmp redis_aof" && \
    $SCP root@${KOTH_IP}:/tmp/redis_aof.tar.gz "${CDIR}/" && ok "Redis AOF" || warn "Redis AOF (skipped)"

log "  → Scorebot keys..."
$SSH root@${KOTH_IP} "docker cp koth-scorebot:/app/keys /tmp/scorebot_keys 2>/dev/null && tar czf /tmp/scorebot_keys.tar.gz -C /tmp scorebot_keys" && \
    $SCP root@${KOTH_IP}:/tmp/scorebot_keys.tar.gz "${CDIR}/" && ok "Scorebot keys" || warn "Scorebot keys (none)"

log "  → Project files (/opt/kothd)..."
$SSH root@${KOTH_IP} "cd /opt && tar czf /tmp/kothd-project.tar.gz --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' --exclude='node_modules' kothd/" && \
    $SCP root@${KOTH_IP}:/tmp/kothd-project.tar.gz "${CDIR}/" && ok "Project files" || warn "Project files failed"

log "  → Environment file..."
$SCP root@${KOTH_IP}:/opt/kothd/.env "${CDIR}/dot-env" && ok ".env" || warn ".env failed"

log "  → Docker images..."
$SSH root@${KOTH_IP} "docker save kothd-scoreboard kothd-scorebot | gzip > /tmp/koth-images.tar.gz" && \
    $SCP root@${KOTH_IP}:/tmp/koth-images.tar.gz "${CDIR}/" && ok "Docker images" || warn "Docker images failed"

log "  → Nginx config..."
$SSH root@${KOTH_IP} "docker cp koth-nginx:/etc/nginx/conf.d /tmp/nginx_conf 2>/dev/null && tar czf /tmp/nginx_conf.tar.gz -C /tmp nginx_conf" && \
    $SCP root@${KOTH_IP}:/tmp/nginx_conf.tar.gz "${CDIR}/" && ok "Nginx config" || warn "Nginx config (skipped)"

# Metadata
$SSH root@${KOTH_IP} "docker volume ls --format '{{.Name}}'" > "${CDIR}/docker-volumes.txt" 2>/dev/null || true
$SSH root@${KOTH_IP} "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'" > "${CDIR}/docker-ps.txt" 2>/dev/null || true
$SSH root@${KOTH_IP} "ip addr show" > "${CDIR}/ip-addr.txt" 2>/dev/null || true
$SSH root@${KOTH_IP} "iptables-save" > "${CDIR}/iptables.txt" 2>/dev/null || true

# Cleanup remote
$SSH root@${KOTH_IP} "rm -f /tmp/koth_db.dump /tmp/koth_db.sql /tmp/redis_dump.rdb /tmp/redis_aof.tar.gz /tmp/scorebot_keys.tar.gz /tmp/kothd-project.tar.gz /tmp/koth-images.tar.gz /tmp/nginx_conf.tar.gz; rm -rf /tmp/scorebot_keys /tmp/redis_aof /tmp/nginx_conf" 2>/dev/null || true

ok "KoTH Main Server backup complete"

# ═══════════════════════════════════════════════════════════════════════
# Helper function for hill backup
# ═══════════════════════════════════════════════════════════════════════
backup_hill() {
    local NUM=$1 IP=$2 CONTAINER=$3 IMAGE=$4 LABEL=$5
    local CDIR="${BACKUP_DIR}/hill${NUM}"
    local STEP=$((NUM + 1))

    echo ""
    log "[${STEP}/5] Backing up Hill ${NUM} — ${LABEL} (${IP})..."

    log "  → Challenge source files..."
    $SSH root@${IP} "tar czf /tmp/hill${NUM}-challenge.tar.gz -C /opt/hill challenge/" && \
        $SCP root@${IP}:/tmp/hill${NUM}-challenge.tar.gz "${CDIR}/" && ok "Challenge files" || warn "Challenge files failed"

    log "  → Docker image..."
    $SSH root@${IP} "docker save ${IMAGE} | gzip > /tmp/hill${NUM}-image.tar.gz" && \
        $SCP root@${IP}:/tmp/hill${NUM}-image.tar.gz "${CDIR}/" && ok "Docker image" || warn "Docker image failed"

    log "  → Container state..."
    $SSH root@${IP} "docker exec ${CONTAINER} tar czf /tmp/state.tar.gz /root/king.txt 2>/dev/null && docker cp ${CONTAINER}:/tmp/state.tar.gz /tmp/hill${NUM}-state.tar.gz" && \
        $SCP root@${IP}:/tmp/hill${NUM}-state.tar.gz "${CDIR}/" && ok "Container state" || warn "Container state (skipped)"

    $SSH root@${IP} "cat /root/king.txt" > "${CDIR}/host-king.txt" 2>/dev/null || true
    $SSH root@${IP} "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'" > "${CDIR}/docker-ps.txt" 2>/dev/null || true
    $SSH root@${IP} "ip addr show" > "${CDIR}/ip-addr.txt" 2>/dev/null || true
    $SSH root@${IP} "iptables-save" > "${CDIR}/iptables.txt" 2>/dev/null || true

    $SSH root@${IP} "rm -f /tmp/hill${NUM}-challenge.tar.gz /tmp/hill${NUM}-image.tar.gz /tmp/hill${NUM}-state.tar.gz" 2>/dev/null || true

    ok "Hill ${NUM} backup complete"
}

# ═══════════════════════════════════════════════════════════════════════
# 2-5. Hills
# ═══════════════════════════════════════════════════════════════════════
backup_hill 1 "${HILL1_IP}" "hill1-web-fortress"      "challenge-web-fortress"     "Web Fortress"
backup_hill 2 "${HILL2_IP}" "hill2-service-bastion"    "challenge-service-bastion"  "Service Bastion"
backup_hill 3 "${HILL3_IP}" "hill3-api-gateway"        "challenge-hill3-api"        "API Gateway"
backup_hill 4 "${HILL4_IP}" "hill4-data-vault"         "challenge-hill4-db"         "Data Vault"

# Also backup Hill 4 container running on Hill 3 host
echo ""
log "  → [Bonus] Hill 4 image on Hill 3 host (${HILL3_IP})..."
$SSH root@${HILL3_IP} "docker save hill4-db-hill4-db 2>/dev/null | gzip > /tmp/hill4-on-hill3.tar.gz" && \
    $SCP root@${HILL3_IP}:/tmp/hill4-on-hill3.tar.gz "${BACKUP_DIR}/hill3/" && ok "Hill 4 image (on hill3 host)" || warn "Hill 4 image on hill3 (skipped)"
$SSH root@${HILL3_IP} "rm -f /tmp/hill4-on-hill3.tar.gz" 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Backup Complete!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Contents:"
find "${BACKUP_DIR}" -type f -exec ls -lh {} \; 2>/dev/null | awk '{printf "  %-10s %s\n", $5, $9}'
echo ""
TOTAL=$(du -sh "${BACKUP_DIR}" | awk '{print $1}')
echo "Total size: ${TOTAL}"
echo "Location:   ${BACKUP_DIR}"
echo ""
echo "To create a single archive:"
echo "  tar czf koth-backup-${TIMESTAMP}.tar.gz -C $(dirname ${BACKUP_DIR}) $(basename ${BACKUP_DIR})"

# Create manifest
cat > "${BACKUP_DIR}/MANIFEST.md" << EOF
# KoTH CTF Backup — ${TIMESTAMP}

## Servers Backed Up
| Server | IP | Role |
|---|---|---|
| Main | ${KOTH_IP} | Scoreboard + Scorebot + DB + Redis + Nginx |
| Hill 1 | ${HILL1_IP} | Web Fortress |
| Hill 2 | ${HILL2_IP} | Service Bastion |
| Hill 3 | ${HILL3_IP} | API Gateway (+ Hill 4 container) |
| Hill 4 | ${HILL4_IP} | Data Vault |

## Key Files
- koth/koth_db.dump — PostgreSQL binary dump (use pg_restore)
- koth/koth_db.sql — PostgreSQL SQL dump (human-readable)
- koth/redis_dump.rdb — Redis snapshot
- koth/dot-env — Environment configuration
- koth/kothd-project.tar.gz — Full /opt/kothd project directory
- koth/koth-images.tar.gz — Docker images (scoreboard + scorebot)
- hill{1-4}/hill*-challenge.tar.gz — Challenge source files
- hill{1-4}/hill*-image.tar.gz — Docker images for each hill

## Restore
See scripts/restore-to-new-vm.sh in the git repository.
EOF

ok "Manifest written to ${BACKUP_DIR}/MANIFEST.md"
