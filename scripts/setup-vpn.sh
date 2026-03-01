#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — WireGuard VPN Setup Script
# Run on: VPN Server (${VPN_SERVER_IP:-YOUR_VPN_IP})
# Creates WireGuard server + 20 team peer configs
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
VPN_SERVER_IP="${VPN_SERVER_IP:-YOUR_VPN_IP}"
VPN_PRIVATE_NET="10.10.0.0/24"       # VPN subnet
VPN_SERVER_ADDR="10.10.0.1/24"
VPN_PORT=51820
VPN_INTERFACE="wg0"
NUM_TEAMS=20
OUTPUT_DIR="/etc/wireguard/clients"
DNS="1.1.1.1"

# Internal networks teams can access
ALLOWED_IPS_SERVER="10.10.0.0/24, ${VPC_SUBNET:-10.x.x.0/20}"

# Pivot DMZ IP (for routing)
PIVOT_IP="${PIVOT_VPC_IP:-10.x.x.4}"

# Hill IPs (direct access)
HILL1_IP="${HILL1_VPC_IP:-10.x.x.2}"
HILL2_IP="${HILL2_VPC_IP:-10.x.x.3}"

# Hill IPs (behind pivot)
HILL3_IP="${HILL3_VPC_IP:-10.x.x.10}"
HILL4_IP="${HILL4_VPC_IP:-10.x.x.11}"

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — VPN Setup"
echo "  Server: ${VPN_SERVER_IP}"
echo "  Teams:  ${NUM_TEAMS}"
echo "════════════════════════════════════════════════════════"

# ── Install WireGuard ─────────────────────────────────────────────────
echo "[1/5] Installing WireGuard..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools qrencode iptables-persistent

# ── Generate Server Keys ─────────────────────────────────────────────
echo "[2/5] Generating server keys..."
mkdir -p /etc/wireguard
mkdir -p "${OUTPUT_DIR}"

if [ ! -f /etc/wireguard/server_private.key ]; then
    wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
    chmod 600 /etc/wireguard/server_private.key
fi

SERVER_PRIVATE_KEY=$(cat /etc/wireguard/server_private.key)
SERVER_PUBLIC_KEY=$(cat /etc/wireguard/server_public.key)

echo "  Server Public Key: ${SERVER_PUBLIC_KEY}"

# ── Generate Server Config ────────────────────────────────────────────
echo "[3/5] Creating server config..."

cat > /etc/wireguard/${VPN_INTERFACE}.conf << EOF
# KoTH CTF — WireGuard Server
[Interface]
Address = ${VPN_SERVER_ADDR}
ListenPort = ${VPN_PORT}
PrivateKey = ${SERVER_PRIVATE_KEY}

# Enable forwarding
PostUp = sysctl -w net.ipv4.ip_forward=1
PostUp = iptables -A FORWARD -i %i -j ACCEPT
PostUp = iptables -A FORWARD -o %i -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostUp = iptables -t nat -A POSTROUTING -o eth1 -j MASQUERADE

PostDown = iptables -D FORWARD -i %i -j ACCEPT
PostDown = iptables -D FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -t nat -D POSTROUTING -o eth1 -j MASQUERADE

EOF

# ── Generate Team Configs ─────────────────────────────────────────────
echo "[4/5] Generating ${NUM_TEAMS} team configurations..."

for i in $(seq 1 ${NUM_TEAMS}); do
    TEAM_NUM=$(printf "%02d" $i)
    TEAM_IP="10.10.0.$((i + 1))"

    # Generate team keys
    TEAM_PRIVATE=$(wg genkey)
    TEAM_PUBLIC=$(echo "${TEAM_PRIVATE}" | wg pubkey)
    TEAM_PSK=$(wg genpsk)

    # Add peer to server config
    cat >> /etc/wireguard/${VPN_INTERFACE}.conf << EOF

# Team ${TEAM_NUM}
[Peer]
PublicKey = ${TEAM_PUBLIC}
PresharedKey = ${TEAM_PSK}
AllowedIPs = ${TEAM_IP}/32

EOF

    # Create client config
    TEAM_CONFIG="${OUTPUT_DIR}/team-${TEAM_NUM}.conf"
    cat > "${TEAM_CONFIG}" << EOF
# KoTH CTF — Team ${TEAM_NUM} VPN Config
# VPN IP: ${TEAM_IP}

[Interface]
Address = ${TEAM_IP}/24
PrivateKey = ${TEAM_PRIVATE}
DNS = ${DNS}

[Peer]
PublicKey = ${SERVER_PUBLIC_KEY}
PresharedKey = ${TEAM_PSK}
Endpoint = ${VPN_SERVER_IP}:${VPN_PORT}
AllowedIPs = ${ALLOWED_IPS_SERVER}
PersistentKeepalive = 25
EOF

    # Generate QR code
    qrencode -t PNG -o "${OUTPUT_DIR}/team-${TEAM_NUM}-qr.png" < "${TEAM_CONFIG}" 2>/dev/null || true

    echo "  ✓ Team ${TEAM_NUM}: ${TEAM_IP} → ${TEAM_CONFIG}"
done

# ── Enable & Start ────────────────────────────────────────────────────
echo "[5/5] Enabling WireGuard..."

# Enable IP forwarding permanently
echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-koth-forward.conf
sysctl -p /etc/sysctl.d/99-koth-forward.conf

# Enable WireGuard service
systemctl enable wg-quick@${VPN_INTERFACE}
systemctl restart wg-quick@${VPN_INTERFACE}

# Add route to hidden networks through pivot
ip route add ${HILL3_VPC_IP:-10.x.x.10}/32 via ${PIVOT_IP} 2>/dev/null || true
ip route add ${HILL4_VPC_IP:-10.x.x.11}/32 via ${PIVOT_IP} 2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ VPN Setup Complete!"
echo "════════════════════════════════════════════════════════"
echo "  Server Public Key: ${SERVER_PUBLIC_KEY}"
echo "  Listening:         ${VPN_SERVER_IP}:${VPN_PORT}"
echo "  Team configs:      ${OUTPUT_DIR}/team-XX.conf"
echo "  QR codes:          ${OUTPUT_DIR}/team-XX-qr.png"
echo ""
echo "  Verify: wg show"
echo "════════════════════════════════════════════════════════"
