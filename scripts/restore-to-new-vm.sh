#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Restore / Migration Script
# Restores a backup to new VM(s)
# ═══════════════════════════════════════════════════════════════════════
#
# Prerequisites on target VM(s):
#   - Ubuntu 22.04+ (or Debian 12+)
#   - Root SSH access
#   - Internet access (to pull base Docker images)
#
# Usage:
#   # === Option A: Full restore from backup archive ===
#   ./restore-to-new-vm.sh --backup-dir ./koth-backup-20260307-120000 \
#       --koth-ip NEW_KOTH_IP \
#       --hill1-ip NEW_HILL1_IP \
#       --hill2-ip NEW_HILL2_IP \
#       --hill3-ip NEW_HILL3_IP \
#       --hill4-ip NEW_HILL4_IP
#
#   # === Option B: Fresh deploy from git (no backup needed) ===
#   ./restore-to-new-vm.sh --fresh \
#       --koth-ip NEW_KOTH_IP \
#       --hill1-ip NEW_HILL1_IP \
#       --hill2-ip NEW_HILL2_IP \
#       --hill3-ip NEW_HILL3_IP \
#       --hill4-ip NEW_HILL4_IP
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────
NEW_SSH_PASS="${NEW_SSH_PASS:-anonyM404.a}"
BACKUP_DIR=""
FRESH=false
KOTH_IP="" HILL1_IP="" HILL2_IP="" HILL3_IP="" HILL4_IP=""
REPO_URL="${REPO_URL:-}"  # Git repo URL if doing fresh deploy
SKIP_HILLS=false
SKIP_KOTH=false

# ── Parse args ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --backup-dir)  BACKUP_DIR="$2"; shift 2 ;;
        --fresh)       FRESH=true; shift ;;
        --koth-ip)     KOTH_IP="$2"; shift 2 ;;
        --hill1-ip)    HILL1_IP="$2"; shift 2 ;;
        --hill2-ip)    HILL2_IP="$2"; shift 2 ;;
        --hill3-ip)    HILL3_IP="$2"; shift 2 ;;
        --hill4-ip)    HILL4_IP="$2"; shift 2 ;;
        --skip-hills)  SKIP_HILLS=true; shift ;;
        --skip-koth)   SKIP_KOTH=true; shift ;;
        --ssh-pass)    NEW_SSH_PASS="$2"; shift 2 ;;
        --repo)        REPO_URL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Validate ──────────────────────────────────────────────────────────
if [[ "$FRESH" == false && -z "$BACKUP_DIR" ]]; then
    echo "ERROR: Must specify --backup-dir or --fresh"
    echo "Run with --help for usage"
    exit 1
fi

if [[ -n "$BACKUP_DIR" && ! -d "$BACKUP_DIR" ]]; then
    echo "ERROR: Backup directory not found: $BACKUP_DIR"
    exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
SSH="sshpass -p ${NEW_SSH_PASS} ssh ${SSH_OPTS}"
SCP="sshpass -p ${NEW_SSH_PASS} scp ${SSH_OPTS} -r"

log()  { echo -e "\033[1;36m[$(date +%H:%M:%S)]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓\033[0m $*"; }
warn() { echo -e "\033[1;33m  ⚠\033[0m $*"; }
fail() { echo -e "\033[1;31m  ✗\033[0m $*"; exit 1; }

# ═══════════════════════════════════════════════════════════════════════
# Install Docker on a remote host
# ═══════════════════════════════════════════════════════════════════════
install_docker_remote() {
    local IP=$1
    log "  → Checking Docker on ${IP}..."
    if $SSH root@${IP} "docker --version" 2>/dev/null; then
        ok "Docker already installed"
        return
    fi
    log "  → Installing Docker on ${IP}..."
    $SSH root@${IP} "apt-get update -qq && apt-get install -y -qq docker.io docker-compose-plugin && systemctl enable --now docker" && \
        ok "Docker installed" || fail "Docker install failed on ${IP}"
}

# ═══════════════════════════════════════════════════════════════════════
# Restore KoTH Main Server
# ═══════════════════════════════════════════════════════════════════════
restore_koth() {
    local IP=$1
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    log "Restoring KoTH Main Server → ${IP}"
    echo "════════════════════════════════════════════════════════════════"

    install_docker_remote "${IP}"

    # Install basic tools
    $SSH root@${IP} "apt-get install -y -qq rsync git sshpass" 2>/dev/null || true

    if [[ "$FRESH" == true ]]; then
        # ── Fresh deploy from source ──────────────────────────────────
        log "  → Fresh deploy from source..."

        # Copy project files
        log "  → Syncing project files..."
        SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
        sshpass -p "${NEW_SSH_PASS}" rsync -avz --delete \
            --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
            --exclude='*.pyc' --exclude='.pytest_cache' --exclude='.ruff_cache' \
            --exclude='node_modules' --exclude='.coverage' \
            -e "ssh ${SSH_OPTS}" \
            "${SCRIPT_DIR}/" "root@${IP}:/opt/kothd/"
        ok "Project files synced"

        # Generate .env if not present
        if ! $SSH root@${IP} "test -f /opt/kothd/.env"; then
            log "  → Generating .env..."
            $SSH root@${IP} "cd /opt/kothd && cp .env.example .env"
            warn "Created .env from example — EDIT IT with correct values!"
        fi

        # Build and start
        log "  → Building and starting containers..."
        $SSH root@${IP} "cd /opt/kothd && docker compose build && docker compose up -d"
        ok "Containers started"

    else
        # ── Restore from backup ───────────────────────────────────────
        local BDIR="${BACKUP_DIR}/koth"

        # Upload project archive
        if [[ -f "${BDIR}/kothd-project.tar.gz" ]]; then
            log "  → Uploading project files..."
            $SCP "${BDIR}/kothd-project.tar.gz" root@${IP}:/tmp/
            $SSH root@${IP} "rm -rf /opt/kothd && cd /opt && tar xzf /tmp/kothd-project.tar.gz && rm /tmp/kothd-project.tar.gz"
            ok "Project files restored"
        fi

        # Restore .env
        if [[ -f "${BDIR}/dot-env" ]]; then
            log "  → Restoring .env..."
            $SCP "${BDIR}/dot-env" root@${IP}:/opt/kothd/.env
            ok ".env restored"
        fi

        # Update hill IPs in .env if new IPs provided
        if [[ -n "$HILL1_IP" ]]; then
            $SSH root@${IP} "sed -i 's/^HILL1_IP=.*/HILL1_IP=${HILL1_IP}/' /opt/kothd/.env"
        fi
        if [[ -n "$HILL2_IP" ]]; then
            $SSH root@${IP} "sed -i 's/^HILL2_IP=.*/HILL2_IP=${HILL2_IP}/' /opt/kothd/.env"
        fi
        if [[ -n "$HILL3_IP" ]]; then
            $SSH root@${IP} "sed -i 's/^HILL3_IP=.*/HILL3_IP=${HILL3_IP}/' /opt/kothd/.env"
        fi
        if [[ -n "$HILL4_IP" ]]; then
            $SSH root@${IP} "sed -i 's/^HILL4_IP=.*/HILL4_IP=${HILL4_IP}/' /opt/kothd/.env"
        fi

        # Load Docker images or rebuild
        if [[ -f "${BDIR}/koth-images.tar.gz" ]]; then
            log "  → Loading Docker images..."
            $SCP "${BDIR}/koth-images.tar.gz" root@${IP}:/tmp/
            $SSH root@${IP} "gunzip -c /tmp/koth-images.tar.gz | docker load && rm /tmp/koth-images.tar.gz"
            ok "Docker images loaded"
        else
            log "  → Building Docker images..."
            $SSH root@${IP} "cd /opt/kothd && docker compose build"
            ok "Docker images built"
        fi

        # Start base services first (DB + Redis)
        log "  → Starting database and Redis..."
        $SSH root@${IP} "cd /opt/kothd && docker compose up -d db redis"
        sleep 5

        # Restore PostgreSQL
        if [[ -f "${BDIR}/koth_db.dump" ]]; then
            log "  → Restoring PostgreSQL..."
            $SCP "${BDIR}/koth_db.dump" root@${IP}:/tmp/
            $SSH root@${IP} "docker cp /tmp/koth_db.dump koth-db:/tmp/ && \
                docker exec koth-db pg_restore -U koth_admin -d koth --clean --if-exists /tmp/koth_db.dump 2>/dev/null; \
                rm /tmp/koth_db.dump"
            ok "PostgreSQL restored"
        elif [[ -f "${BDIR}/koth_db.sql" ]]; then
            log "  → Restoring PostgreSQL (SQL)..."
            $SCP "${BDIR}/koth_db.sql" root@${IP}:/tmp/
            $SSH root@${IP} "docker cp /tmp/koth_db.sql koth-db:/tmp/ && \
                docker exec koth-db psql -U koth_admin -d koth -f /tmp/koth_db.sql 2>/dev/null; \
                rm /tmp/koth_db.sql"
            ok "PostgreSQL restored (SQL)"
        fi

        # Restore Redis
        if [[ -f "${BDIR}/redis_dump.rdb" ]]; then
            log "  → Restoring Redis..."
            $SSH root@${IP} "docker compose -f /opt/kothd/docker-compose.yml stop redis"
            $SCP "${BDIR}/redis_dump.rdb" root@${IP}:/tmp/
            $SSH root@${IP} "docker cp /tmp/redis_dump.rdb koth-redis:/data/dump.rdb && rm /tmp/redis_dump.rdb"
            $SSH root@${IP} "docker compose -f /opt/kothd/docker-compose.yml start redis"
            ok "Redis restored"
        fi

        # Restore Nginx config
        if [[ -f "${BDIR}/nginx_conf.tar.gz" ]]; then
            log "  → Restoring Nginx config..."
            $SCP "${BDIR}/nginx_conf.tar.gz" root@${IP}:/tmp/
            $SSH root@${IP} "tar xzf /tmp/nginx_conf.tar.gz -C /tmp && docker cp /tmp/nginx_conf/. koth-nginx:/etc/nginx/conf.d/ && rm -rf /tmp/nginx_conf /tmp/nginx_conf.tar.gz"
            ok "Nginx config restored"
        fi

        # Start all services
        log "  → Starting all containers..."
        $SSH root@${IP} "cd /opt/kothd && docker compose up -d"
        ok "All containers started"
    fi

    # Verify
    log "  → Verifying..."
    sleep 5
    $SSH root@${IP} "docker ps --format 'table {{.Names}}\t{{.Status}}'"
    ok "KoTH Main Server restored"
}

# ═══════════════════════════════════════════════════════════════════════
# Restore a Hill Server
# ═══════════════════════════════════════════════════════════════════════
restore_hill() {
    local NUM=$1 IP=$2 HILL_DIR=$3 HILL_NAME=$4

    echo ""
    echo "════════════════════════════════════════════════════════════════"
    log "Restoring Hill ${NUM} — ${HILL_NAME} → ${IP}"
    echo "════════════════════════════════════════════════════════════════"

    install_docker_remote "${IP}"

    $SSH root@${IP} "apt-get install -y -qq rsync sshpass" 2>/dev/null || true

    # Init king.txt on host
    $SSH root@${IP} "echo nobody > /root/king.txt && chmod 644 /root/king.txt"

    if [[ "$FRESH" == true ]]; then
        # ── Fresh deploy from source ──────────────────────────────────
        SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
        local SRC="${SCRIPT_DIR}/hills/${HILL_DIR}"

        if [[ ! -d "$SRC" ]]; then
            warn "Source directory not found: ${SRC} — skipping"
            return
        fi

        log "  → Syncing challenge files..."
        $SSH root@${IP} "mkdir -p /opt/hill/challenge"
        sshpass -p "${NEW_SSH_PASS}" rsync -avz --delete \
            -e "ssh ${SSH_OPTS}" \
            "${SRC}/" "root@${IP}:/opt/hill/challenge/"
        ok "Challenge files synced"

        $SSH root@${IP} "chmod +x /opt/hill/challenge/entrypoint.sh 2>/dev/null || true"

        log "  → Building and starting container..."
        $SSH root@${IP} "cd /opt/hill/challenge && docker compose down 2>/dev/null || true && docker compose build --no-cache && docker compose up -d"
        ok "Container started"

    else
        # ── Restore from backup ───────────────────────────────────────
        local BDIR="${BACKUP_DIR}/hill${NUM}"

        # Restore challenge source (preferred — allows rebuild)
        if [[ -f "${BDIR}/hill${NUM}-challenge.tar.gz" ]]; then
            log "  → Uploading challenge files..."
            $SCP "${BDIR}/hill${NUM}-challenge.tar.gz" root@${IP}:/tmp/
            $SSH root@${IP} "rm -rf /opt/hill/challenge && mkdir -p /opt/hill && cd /opt/hill && tar xzf /tmp/hill${NUM}-challenge.tar.gz && rm /tmp/hill${NUM}-challenge.tar.gz"
            ok "Challenge files restored"

            $SSH root@${IP} "chmod +x /opt/hill/challenge/entrypoint.sh 2>/dev/null || true"

            log "  → Building container from source..."
            $SSH root@${IP} "cd /opt/hill/challenge && docker compose down 2>/dev/null || true && docker compose build --no-cache && docker compose up -d"
            ok "Container built and started"

        elif [[ -f "${BDIR}/hill${NUM}-image.tar.gz" ]]; then
            # Fallback: load pre-built image
            log "  → Loading Docker image..."
            $SCP "${BDIR}/hill${NUM}-image.tar.gz" root@${IP}:/tmp/
            $SSH root@${IP} "gunzip -c /tmp/hill${NUM}-image.tar.gz | docker load && rm /tmp/hill${NUM}-image.tar.gz"
            ok "Docker image loaded"

            if [[ -f "${BDIR}/hill${NUM}-challenge.tar.gz" ]]; then
                $SCP "${BDIR}/hill${NUM}-challenge.tar.gz" root@${IP}:/tmp/
                $SSH root@${IP} "mkdir -p /opt/hill && cd /opt/hill && tar xzf /tmp/hill${NUM}-challenge.tar.gz && rm /tmp/hill${NUM}-challenge.tar.gz"
            fi

            log "  → Starting container..."
            $SSH root@${IP} "cd /opt/hill/challenge && docker compose up -d"
            ok "Container started"
        else
            warn "No backup files found for Hill ${NUM}"
        fi
    fi

    # Verify
    log "  → Verifying..."
    sleep 3
    $SSH root@${IP} "docker ps --format 'table {{.Names}}\t{{.Status}}'"
    ok "Hill ${NUM} — ${HILL_NAME} restored"
}

# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  KoTH CTF — Restore / Migration"
if [[ "$FRESH" == true ]]; then
    echo "  Mode: Fresh deploy from source"
else
    echo "  Mode: Restore from backup (${BACKUP_DIR})"
fi
echo "════════════════════════════════════════════════════════════════"

# Restore KoTH main server
if [[ "$SKIP_KOTH" == false && -n "$KOTH_IP" ]]; then
    restore_koth "${KOTH_IP}"
fi

# Restore hills
if [[ "$SKIP_HILLS" == false ]]; then
    [[ -n "$HILL1_IP" ]] && restore_hill 1 "${HILL1_IP}" "hill1-web"      "Web Fortress"
    [[ -n "$HILL2_IP" ]] && restore_hill 2 "${HILL2_IP}" "hill2-services"  "Service Bastion"
    [[ -n "$HILL3_IP" ]] && restore_hill 3 "${HILL3_IP}" "hill3-api"       "API Gateway"
    [[ -n "$HILL4_IP" ]] && restore_hill 4 "${HILL4_IP}" "hill4-db"        "Data Vault"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Migration Complete!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Post-migration checklist:"
echo "  1. Update DNS records if applicable"
echo "  2. Verify .env on KoTH server has correct hill IPs"
echo "  3. Register hills via admin API:"
echo "     curl -X POST http://\${KOTH_IP}:8000/api/admin/hills \\"
echo "       -H 'X-Admin-Token: YOUR_TOKEN' \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"name\":\"Web Fortress\",\"ip\":\"HILL1_IP\",\"port\":22}'"
echo "  4. Test scorebot connectivity: curl http://\${KOTH_IP}:8081/health"
echo "  5. Run smoke test: ./scripts/smoke-test.sh"
echo ""
