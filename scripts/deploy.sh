#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Single-Server Deployment Script
# Deploys the full platform (scoreboard + scorebot + nginx + DB + Redis)
# on one machine using Docker Compose.
#
# Usage:
#   ssh root@SERVER 'bash -s' < scripts/deploy.sh          # remote
#   sudo ./scripts/deploy.sh                                 # local
#
# Prerequisites: Ubuntu/Debian with root or sudo.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_URL="${KOTH_REPO:-https://github.com/mhrsq/kothd.git}"
INSTALL_DIR="${KOTH_DIR:-/opt/kothd}"
BRANCH="${KOTH_BRANCH:-main}"

# ── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Preflight checks ─────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Must run as root. Use: sudo $0"
    exit 1
fi

info "KoTH CTF — Single-Server Deployment"
info "Target directory: ${INSTALL_DIR}"
echo ""

# ── 1. Install Docker if missing ─────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
        tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    info "Docker installed: $(docker --version)"
else
    info "Docker already installed: $(docker --version)"
fi

# Verify docker compose plugin
if ! docker compose version &>/dev/null; then
    error "docker compose plugin not found. Install docker-compose-plugin."
    exit 1
fi

# ── 2. Install Git if missing ────────────────────────────────────────
if ! command -v git &>/dev/null; then
    info "Installing Git..."
    apt-get install -y -qq git
fi

# ── 3. Clone or update repo ──────────────────────────────────────────
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git fetch origin "$BRANCH"
    git reset --hard "origin/${BRANCH}"
else
    info "Cloning repository..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── 4. Generate .env if not present ──────────────────────────────────
if [[ ! -f .env ]]; then
    info "Generating secure .env..."
    bash scripts/generate-env.sh .env
    echo ""
else
    info ".env already exists — keeping current values"
fi

# ── 5. Create SSH key pair for scorebot ──────────────────────────────
KEYS_DIR="${INSTALL_DIR}/keys"
mkdir -p "$KEYS_DIR"
if [[ ! -f "${KEYS_DIR}/scorebot_key" ]]; then
    info "Generating scorebot SSH key pair..."
    ssh-keygen -t ed25519 -f "${KEYS_DIR}/scorebot_key" -N "" -C "koth-scorebot"
    chmod 600 "${KEYS_DIR}/scorebot_key"
    info "Public key: ${KEYS_DIR}/scorebot_key.pub"
fi

# ── 6. Build and start containers ────────────────────────────────────
info "Building Docker images..."
docker compose build --quiet

info "Starting services..."
docker compose up -d

# ── 7. Wait for services to be healthy ───────────────────────────────
info "Waiting for services to be ready..."
MAX_WAIT=60
WAITED=0
while [[ $WAITED -lt $MAX_WAIT ]]; do
    if docker compose ps --format json 2>/dev/null | grep -q '"Health":"healthy"' || \
       curl -sf http://localhost:8000/api/health &>/dev/null; then
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    printf "."
done
echo ""

# ── 8. Smoke test ────────────────────────────────────────────────────
if curl -sf http://localhost:8000/api/health | grep -q '"version"'; then
    info "Scoreboard API is healthy!"
else
    warn "Scoreboard not yet responding on :8000 — check: docker compose logs scoreboard"
fi

if curl -sf http://localhost/api/health | grep -q '"version"'; then
    info "Nginx reverse proxy is healthy!"
else
    warn "Nginx not yet responding on :80 — check: docker compose logs nginx"
fi

# ── 9. Print summary ─────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════"
info "KoTH CTF Platform deployed successfully!"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "  Scoreboard:  http://$(hostname -I | awk '{print $1}')"
echo "  Admin panel: http://$(hostname -I | awk '{print $1}')/admin.html"
echo "  API direct:  http://localhost:8000/api/health"
echo ""

# Extract admin token from .env
ADMIN_TOKEN=$(grep '^API_ADMIN_TOKEN=' .env | cut -d= -f2)
echo "  Admin Token: ${ADMIN_TOKEN}"
echo ""
echo "  Manage:  cd ${INSTALL_DIR} && docker compose [logs|ps|down|restart]"
echo "  Tests:   cd ${INSTALL_DIR} && bash scripts/smoke-test.sh"
echo ""
