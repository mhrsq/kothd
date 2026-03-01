#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — OpenVPN Setup Script
# Run on: VPN Server (${VPN_SERVER_IP:-YOUR_VPN_IP})
# Creates OpenVPN server + 20 team client configs (.ovpn)
# Alternative to WireGuard — supports wider client compatibility
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
VPN_SERVER_IP="${VPN_SERVER_IP:-YOUR_VPN_IP}"
VPN_SUBNET="10.11.0.0"               # OpenVPN uses separate subnet from WireGuard
VPN_NETMASK="255.255.255.0"
VPN_PORT=1194
VPN_PROTO="udp"
NUM_TEAMS=20
OUTPUT_DIR="/etc/openvpn/clients"
EASY_RSA_DIR="/etc/openvpn/easy-rsa"

# Internal networks teams can access
PUSH_ROUTE_VPN="10.10.0.0 255.255.255.0"      # WireGuard subnet (if dual-stack)
PUSH_ROUTE_HILLS="${HILL_NETWORK:-10.0.0.0} ${HILL_NETMASK:-255.255.255.0}"   # Hill network

# Hill IPs
HILL1_IP="${HILL1_VPC_IP:-10.x.x.2}"
HILL2_IP="${HILL2_VPC_IP:-10.x.x.3}"
HILL3_IP="${HILL3_VPC_IP:-10.x.x.10}"
HILL4_IP="${HILL4_VPC_IP:-10.x.x.11}"
PIVOT_IP="${PIVOT_VPC_IP:-10.x.x.4}"

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — OpenVPN Setup"
echo "  Server: ${VPN_SERVER_IP}:${VPN_PORT}/${VPN_PROTO}"
echo "  Teams:  ${NUM_TEAMS}"
echo "════════════════════════════════════════════════════════"

# ── Install OpenVPN + Easy-RSA ────────────────────────────────────────
echo "[1/6] Installing OpenVPN & Easy-RSA..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openvpn easy-rsa iptables-persistent

# ── Setup Easy-RSA PKI ────────────────────────────────────────────────
echo "[2/6] Setting up PKI with Easy-RSA..."
mkdir -p "${EASY_RSA_DIR}"
cp -r /usr/share/easy-rsa/* "${EASY_RSA_DIR}/" 2>/dev/null || true

cd "${EASY_RSA_DIR}"

# Init PKI
if [ ! -d "${EASY_RSA_DIR}/pki" ]; then
    ./easyrsa --batch init-pki

    # Build CA (no password)
    EASYRSA_BATCH=1 EASYRSA_REQ_CN="KoTH-KoTH-2026-CA" \
        ./easyrsa --batch build-ca nopass

    # Generate server key + cert
    EASYRSA_BATCH=1 \
        ./easyrsa --batch build-server-full koth-vpn-server nopass

    # Generate DH parameters
    ./easyrsa --batch gen-dh

    # Generate TLS auth key
    openvpn --genkey secret /etc/openvpn/ta.key

    echo "  ✓ PKI initialized"
else
    echo "  ⚡ PKI already exists, skipping..."
fi

# ── Generate Server Config ────────────────────────────────────────────
echo "[3/6] Creating server config..."

cat > /etc/openvpn/server.conf << EOF
# ═══════════════════════════════════════════════════════
# KoTH CTF — OpenVPN Server Configuration
# ═══════════════════════════════════════════════════════

port ${VPN_PORT}
proto ${VPN_PROTO}
dev tun

# Certificates
ca ${EASY_RSA_DIR}/pki/ca.crt
cert ${EASY_RSA_DIR}/pki/issued/koth-vpn-server.crt
key ${EASY_RSA_DIR}/pki/private/koth-vpn-server.key
dh ${EASY_RSA_DIR}/pki/dh.pem
tls-auth /etc/openvpn/ta.key 0

# Network
server ${VPN_SUBNET} ${VPN_NETMASK}
topology subnet

# Push routes to clients
push "route ${PUSH_ROUTE_HILLS}"

# Client isolation — teams cannot see each other
client-to-client
# Use ipp.txt to persist client-IP mappings
ifconfig-pool-persist /etc/openvpn/ipp.txt

# Client config directory for per-team static IPs
client-config-dir /etc/openvpn/ccd

# Security
cipher AES-256-GCM
auth SHA256
tls-version-min 1.2
tls-cipher TLS-ECDHE-ECDSA-WITH-AES-256-GCM-SHA384:TLS-ECDHE-RSA-WITH-AES-256-GCM-SHA384

# Keep alive
keepalive 10 120
persist-key
persist-tun

# Logging
status /var/log/openvpn/status.log
log-append /var/log/openvpn/server.log
verb 3
mute 20

# Max clients
max-clients 25

# Run as unprivileged after init
user nobody
group nogroup

# Compress (compatible mode)
compress lz4-v2
push "compress lz4-v2"

# DNS
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 8.8.8.8"
EOF

# Create log dir and CCD dir
mkdir -p /var/log/openvpn
mkdir -p /etc/openvpn/ccd
mkdir -p "${OUTPUT_DIR}"

# ── Generate Client Configs ───────────────────────────────────────────
echo "[4/6] Generating ${NUM_TEAMS} team client configurations..."

cd "${EASY_RSA_DIR}"

for i in $(seq 1 ${NUM_TEAMS}); do
    TEAM_NUM=$(printf "%02d" $i)
    CLIENT_NAME="team-${TEAM_NUM}"
    TEAM_IP="10.11.0.$((i + 1))"  # team-01 = 10.11.0.2, etc.

    # Generate client cert (skip if exists)
    if [ ! -f "${EASY_RSA_DIR}/pki/issued/${CLIENT_NAME}.crt" ]; then
        EASYRSA_BATCH=1 \
            ./easyrsa --batch build-client-full "${CLIENT_NAME}" nopass
    fi

    # Create CCD entry for static IP assignment
    cat > /etc/openvpn/ccd/${CLIENT_NAME} << EOF2
ifconfig-push ${TEAM_IP} ${VPN_NETMASK}
EOF2

    # Read certs for inline config
    CA_CERT=$(cat "${EASY_RSA_DIR}/pki/ca.crt")
    CLIENT_CERT=$(openssl x509 -in "${EASY_RSA_DIR}/pki/issued/${CLIENT_NAME}.crt")
    CLIENT_KEY=$(cat "${EASY_RSA_DIR}/pki/private/${CLIENT_NAME}.key")
    TA_KEY=$(cat /etc/openvpn/ta.key)

    # Generate unified .ovpn config
    cat > "${OUTPUT_DIR}/${CLIENT_NAME}.ovpn" << EOF3
# ═══════════════════════════════════════════════════════
# KoTH CTF — Team ${TEAM_NUM} OpenVPN Config
# VPN IP: ${TEAM_IP}
# ═══════════════════════════════════════════════════════

client
dev tun
proto ${VPN_PROTO}
remote ${VPN_SERVER_IP} ${VPN_PORT}

resolv-retry infinite
nobind
persist-key
persist-tun

# Security
cipher AES-256-GCM
auth SHA256
key-direction 1

# Compression
compress lz4-v2

# Verify server cert
remote-cert-tls server

# Logging
verb 3
mute 20

<ca>
${CA_CERT}
</ca>

<cert>
${CLIENT_CERT}
</cert>

<key>
${CLIENT_KEY}
</key>

<tls-auth>
${TA_KEY}
</tls-auth>
EOF3

    chmod 600 "${OUTPUT_DIR}/${CLIENT_NAME}.ovpn"
    echo "  ✓ Team ${TEAM_NUM}: ${TEAM_IP} → ${OUTPUT_DIR}/${CLIENT_NAME}.ovpn"
done

# ── Enable IP Forwarding & NAT ────────────────────────────────────────
echo "[5/6] Configuring routing & firewall..."

# Enable IP forwarding
echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-koth-openvpn.conf
sysctl -p /etc/sysctl.d/99-koth-openvpn.conf

# NAT for OpenVPN clients
iptables -t nat -C POSTROUTING -s ${VPN_SUBNET}/24 -o eth0 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s ${VPN_SUBNET}/24 -o eth0 -j MASQUERADE

iptables -t nat -C POSTROUTING -s ${VPN_SUBNET}/24 -o eth1 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s ${VPN_SUBNET}/24 -o eth1 -j MASQUERADE

# Allow forwarding from tun0
iptables -C FORWARD -i tun0 -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i tun0 -j ACCEPT
iptables -C FORWARD -o tun0 -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -o tun0 -j ACCEPT

# Persist firewall rules
iptables-save > /etc/iptables/rules.v4

# Routes to hidden networks
ip route add ${HILL3_IP}/32 via ${PIVOT_IP} 2>/dev/null || true
ip route add ${HILL4_IP}/32 via ${PIVOT_IP} 2>/dev/null || true

# ── Start OpenVPN ─────────────────────────────────────────────────────
echo "[6/6] Starting OpenVPN..."

systemctl enable openvpn@server
systemctl restart openvpn@server

# Wait for startup
sleep 3
if systemctl is-active --quiet openvpn@server; then
    echo "  ✓ OpenVPN server running"
else
    echo "  ✗ OpenVPN failed to start, checking logs..."
    journalctl -u openvpn@server --no-pager -n 20
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ OpenVPN Setup Complete!"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Server:    ${VPN_SERVER_IP}:${VPN_PORT}/${VPN_PROTO}"
echo "  Subnet:    ${VPN_SUBNET}/24"
echo "  Configs:   ${OUTPUT_DIR}/team-XX.ovpn"
echo "  Log:       /var/log/openvpn/server.log"
echo "  Status:    /var/log/openvpn/status.log"
echo ""
echo "  Distribute .ovpn files to teams."
echo "  Teams can connect using:"
echo "    - OpenVPN GUI (Windows)"
echo "    - OpenVPN Connect (macOS/iOS/Android)"
echo "    - sudo openvpn --config team-XX.ovpn (Linux)"
echo ""
echo "  ─── Dual Stack Note ───"
echo "  WireGuard (wg0):  10.10.0.0/24  port 51820/UDP"
echo "  OpenVPN  (tun0):  10.11.0.0/24  port 1194/UDP"
echo "  Both can access hill networks via ${VPC_SUBNET:-10.x.x.0/20}"
echo "════════════════════════════════════════════════════════"
