#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — KoTH Server Setup Script
# Run on: KoTH Server (${KOTH_SERVER_IP:-YOUR_KOTH_IP})
# Deploys scoreboard, scorebot, monitoring stack via Docker Compose
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

KOTH_DIR="/opt/koth"

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — KoTH Server Setup"
echo "  Server: ${KOTH_SERVER_IP:-YOUR_KOTH_IP}"
echo "════════════════════════════════════════════════════════"

# ── Install Dependencies ──────────────────────────────────────────────
echo "[1/6] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq \
    docker.io docker-compose-plugin \
    git curl wget jq htop tmux \
    ufw fail2ban

# ── Configure Firewall ───────────────────────────────────────────────
echo "[2/6] Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# SSH
ufw allow 22/tcp

# Scoreboard (via Nginx)
ufw allow 80/tcp
ufw allow 443/tcp

# Grafana (proxied via Nginx, but allow direct for fallback)
ufw allow 3000/tcp

# Prometheus (internal only — restrict to VPC)
ufw allow from 10.46.0.0/20 to any port 9090

# Internal API (restrict to VPC)
ufw allow from 10.46.0.0/20 to any port 8000
ufw allow from ${VPC_SUBNET:-10.x.x.0/20} to any port 8000

# Scorebot (restrict to VPC)
ufw allow from 10.46.0.0/20 to any port 8081
ufw allow from ${VPC_SUBNET:-10.x.x.0/20} to any port 8081

ufw --force enable

# ── Configure Fail2Ban ───────────────────────────────────────────────
echo "[3/6] Configuring fail2ban..."
cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 600
findtime = 600

[nginx-http-auth]
enabled = true
port = http,https
filter = nginx-http-auth
logpath = /var/log/nginx/error.log
maxretry = 5
bantime = 600
EOF

systemctl enable fail2ban
systemctl restart fail2ban

# ── Prepare Project Files ────────────────────────────────────────────
echo "[4/6] Preparing project directory..."
mkdir -p ${KOTH_DIR}

# Check if files are already deployed
if [ -f "${KOTH_DIR}/docker-compose.yml" ]; then
    echo "  Project files already exist. Updating..."
fi

echo "  Copy project files to ${KOTH_DIR} before running step 5"
echo "  Use: scp -r ./* root@${KOTH_SERVER_IP:-YOUR_KOTH_IP}:${KOTH_DIR}/"

# ── Docker Setup ─────────────────────────────────────────────────────
echo "[5/6] Configuring Docker..."
systemctl enable docker
systemctl start docker

# Create Docker network if not exists
docker network create koth-internal 2>/dev/null || true

# Prune old images
docker system prune -f 2>/dev/null || true

# ── Generate SSH Keys for Scorebot ───────────────────────────────────
echo "[6/6] Generating scorebot SSH keys..."
mkdir -p ${KOTH_DIR}/scorebot-keys

if [ ! -f ${KOTH_DIR}/scorebot-keys/id_rsa ]; then
    ssh-keygen -t rsa -b 4096 -f ${KOTH_DIR}/scorebot-keys/id_rsa -N "" -C "scorebot@koth"
    echo "  SSH key generated: ${KOTH_DIR}/scorebot-keys/id_rsa.pub"
else
    echo "  SSH key already exists."
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ KoTH Server Base Setup Complete!"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo "  1. Copy project files: scp -r ./* root@${KOTH_SERVER_IP:-YOUR_KOTH_IP}:${KOTH_DIR}/"
echo "  2. Copy .env file:     scp .env root@${KOTH_SERVER_IP:-YOUR_KOTH_IP}:${KOTH_DIR}/"
echo "  3. Build & start:      cd ${KOTH_DIR} && docker compose up -d --build"
echo "  4. Check status:       docker compose ps"
echo "  5. View logs:          docker compose logs -f"
echo ""
echo "  Dashboard: http://${KOTH_SERVER_IP:-YOUR_KOTH_IP}"
echo "  Grafana:   http://${KOTH_SERVER_IP:-YOUR_KOTH_IP}/grafana"
echo "════════════════════════════════════════════════════════"
