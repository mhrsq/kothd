#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Secure .env Generator
# Generates .env with cryptographically random passwords.
# Usage: ./scripts/generate-env.sh [--output .env]
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

OUTPUT="${1:-.env}"

# ── helpers ───────────────────────────────────────────────────────────
rand_pass() { openssl rand -base64 "${1:-32}" | tr -d '/+=' | head -c "${2:-32}"; }
rand_hex()  { openssl rand -hex "${1:-16}"; }

POSTGRES_PASSWORD=$(rand_pass 32 32)
REDIS_PASSWORD=$(rand_pass 24 24)
API_SECRET_KEY=$(rand_hex 32)
API_ADMIN_TOKEN=$(rand_hex 24)
HILL_SSH_PASS=$(rand_pass 24 24)
REGISTRATION_CODE=$(rand_pass 8 8 | tr '[:lower:]' '[:upper:]')
VPN_SSH_PASS=$(rand_pass 24 24)

cat > "$OUTPUT" <<EOF
# =============================================================
# KoTH CTF Platform — Environment Configuration
# Auto-generated on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# =============================================================

# ── Database ──────────────────────────────────────────────────
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=koth
POSTGRES_USER=koth_admin
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# ── Redis ─────────────────────────────────────────────────────
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=${REDIS_PASSWORD}

# ── API ───────────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
API_SECRET_KEY=${API_SECRET_KEY}
API_ADMIN_TOKEN=${API_ADMIN_TOKEN}
API_DEBUG=false

# ── Tick Engine ───────────────────────────────────────────────
TICK_INTERVAL=60
TICK_GRACE_PERIOD=300
TICK_FREEZE_BEFORE_END=1800
GAME_DURATION_HOURS=6

# ── Scoring ───────────────────────────────────────────────────
BASE_POINTS=10
PIVOT_MULTIPLIER=1.5
FIRST_BLOOD_BONUS=50
DEFENSE_STREAK_BONUS=5

# ── Scorebot ──────────────────────────────────────────────────
SCOREBOT_HOST=scorebot
SCOREBOT_PORT=8081
SCOREBOT_CHECK_TIMEOUT=15
HILL_SSH_USER=root
HILL_SSH_PASS=${HILL_SSH_PASS}

# ── Registration ──────────────────────────────────────────────
REGISTRATION_CODE=${REGISTRATION_CODE}

# ── Branding ──────────────────────────────────────────────────
EVENT_NAME=KoTH CTF
EVENT_SUBTITLE=King of the Hill Competition
EOF

chmod 600 "$OUTPUT"

echo "✔ Generated $OUTPUT with secure random credentials"
echo ""
echo "  ADMIN TOKEN : ${API_ADMIN_TOKEN}"
echo "  REG CODE    : ${REGISTRATION_CODE}"
echo ""
echo "Keep this file safe. Regenerate with: ./scripts/generate-env.sh"
