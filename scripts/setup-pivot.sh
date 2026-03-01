#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# KoTH CTF — Pivot DMZ Setup Script
# Run on: Pivot DMZ Server (${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP})
# Configures dual-homed routing between VPN net and hidden hills
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "════════════════════════════════════════════════════════"
echo "  KoTH CTF — Pivot DMZ Setup"
echo "  Server: ${PIVOT_PUBLIC_IP:-YOUR_PIVOT_IP} (${PIVOT_VPC_IP:-10.x.x.4})"
echo "════════════════════════════════════════════════════════"

# ── Enable Forwarding ─────────────────────────────────────────────────
echo "[1/4] Enabling IP forwarding..."
echo "net.ipv4.ip_forward = 1" > /etc/sysctl.d/99-koth-pivot.conf
sysctl -p /etc/sysctl.d/99-koth-pivot.conf

# ── Install Utilities ─────────────────────────────────────────────────
echo "[2/4] Installing required packages..."
apt-get update -qq
apt-get install -y -qq iptables iptables-persistent nmap netcat-openbsd docker.io docker-compose-plugin

# ── Configure Firewall / NAT ─────────────────────────────────────────
echo "[3/4] Configuring iptables rules..."

# Flush existing rules
iptables -F
iptables -t nat -F
iptables -X

# Default policies
iptables -P INPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -P OUTPUT ACCEPT

# Allow established/related
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow SSH
iptables -A INPUT -p tcp --dport 22 -j ACCEPT

# Allow ICMP
iptables -A INPUT -p icmp -j ACCEPT
iptables -A FORWARD -p icmp -j ACCEPT

# ── Port Forwarding: Hidden Hills (behind pivot) ─────────────────────
# Hill 3 (API) — ${HILL3_VPC_IP:-10.x.x.10} behind this pivot
# Teams connect to pivot:8080 → forwards to Hill 3:80
# Teams connect to pivot:8443 → forwards to Hill 3:443
iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination ${HILL3_VPC_IP:-10.x.x.10}:80
iptables -t nat -A PREROUTING -p tcp --dport 8443 -j DNAT --to-destination ${HILL3_VPC_IP:-10.x.x.10}:443

# Hill 4 (Data) — ${HILL4_VPC_IP:-10.x.x.11} behind this pivot
# Teams connect to pivot:9090 → forwards to Hill 4:80
# Teams connect to pivot:5432 → forwards to Hill 4:5432
# Teams connect to pivot:3306 → forwards to Hill 4:3306
iptables -t nat -A PREROUTING -p tcp --dport 9090 -j DNAT --to-destination ${HILL4_VPC_IP:-10.x.x.11}:80
iptables -t nat -A PREROUTING -p tcp --dport 5432 -j DNAT --to-destination ${HILL4_VPC_IP:-10.x.x.11}:5432
iptables -t nat -A PREROUTING -p tcp --dport 3306 -j DNAT --to-destination ${HILL4_VPC_IP:-10.x.x.11}:3306

# SSH forwarding for king.txt (scorebot needs direct SSH)
# pivot:2210 → Hill 3 SSH
# pivot:2211 → Hill 4 SSH
iptables -t nat -A PREROUTING -p tcp --dport 2210 -j DNAT --to-destination ${HILL3_VPC_IP:-10.x.x.10}:22
iptables -t nat -A PREROUTING -p tcp --dport 2211 -j DNAT --to-destination ${HILL4_VPC_IP:-10.x.x.11}:22

# Masquerade outgoing traffic
iptables -t nat -A POSTROUTING -j MASQUERADE

# Forward traffic to hidden hills
iptables -A FORWARD -d ${HILL3_VPC_IP:-10.x.x.10} -j ACCEPT
iptables -A FORWARD -d ${HILL4_VPC_IP:-10.x.x.11} -j ACCEPT
iptables -A FORWARD -s ${HILL3_VPC_IP:-10.x.x.10} -j ACCEPT
iptables -A FORWARD -s ${HILL4_VPC_IP:-10.x.x.11} -j ACCEPT

# Save rules
netfilter-persistent save 2>/dev/null || iptables-save > /etc/iptables/rules.v4

# ── Pivot Vulnerable Service (Docker) ────────────────────────────────
echo "[4/4] Setting up pivot challenge service..."

mkdir -p /opt/pivot-challenge

cat > /opt/pivot-challenge/docker-compose.yml << 'DOCKEREOF'
version: "3.8"
services:
  # Intentionally vulnerable SSH jump host
  pivot-ssh:
    image: ubuntu:22.04
    container_name: pivot-ssh
    command: >
      bash -c "
        apt-get update -qq &&
        apt-get install -y openssh-server sudo &&
        mkdir -p /run/sshd &&
        echo 'root:pivot2026' | chpasswd &&
        echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config &&
        useradd -m -s /bin/bash ctfuser &&
        echo 'ctfuser:weakpass123' | chpasswd &&
        echo 'ctfuser ALL=(ALL) NOPASSWD: /usr/bin/nmap, /usr/bin/ss, /usr/bin/ip' >> /etc/sudoers &&
        /usr/sbin/sshd -D
      "
    ports:
      - "2222:22"
    networks:
      - pivot_net
    restart: unless-stopped

  # Simple web service on pivot (info disclosure vuln)
  pivot-web:
    image: nginx:alpine
    container_name: pivot-web
    volumes:
      - ./web:/usr/share/nginx/html:ro
    ports:
      - "80:80"
    networks:
      - pivot_net
    restart: unless-stopped

networks:
  pivot_net:
    driver: bridge
DOCKEREOF

# Create a simple web page with "hints"
mkdir -p /opt/pivot-challenge/web

cat > /opt/pivot-challenge/web/index.html << 'HTMLEOF'
<!DOCTYPE html>
<html><head><title>DMZ Gateway</title></head>
<body>
<h1>DMZ Network Gateway</h1>
<p>Authorized personnel only.</p>
<!-- TODO: Remove debug info before competition -->
<!-- Internal nets: ${HILL3_VPC_IP:-10.x.x.10} (API), ${HILL4_VPC_IP:-10.x.x.11} (Data) -->
<!-- SSH jump: port 2222, user: ctfuser -->
</body>
</html>
HTMLEOF

cat > /opt/pivot-challenge/web/robots.txt << 'ROBOTSEOF'
User-agent: *
Disallow: /internal/
Disallow: /debug/
Disallow: /.env
ROBOTSEOF

mkdir -p /opt/pivot-challenge/web/internal
cat > /opt/pivot-challenge/web/internal/network-map.json << 'JSONEOF'
{
  "dmz": "${PIVOT_VPC_IP:-10.x.x.4}",
  "hidden_services": [
    {"name": "api-server", "ip": "${HILL3_VPC_IP:-10.x.x.10}", "ports": [80, 443, 22]},
    {"name": "data-server", "ip": "${HILL4_VPC_IP:-10.x.x.11}", "ports": [80, 5432, 3306, 22]}
  ],
  "forwarding_rules": {
    "8080": "${HILL3_VPC_IP:-10.x.x.10}:80",
    "8443": "${HILL3_VPC_IP:-10.x.x.10}:443",
    "9090": "${HILL4_VPC_IP:-10.x.x.11}:80",
    "2210": "${HILL3_VPC_IP:-10.x.x.10}:22",
    "2211": "${HILL4_VPC_IP:-10.x.x.11}:22"
  }
}
JSONEOF

# Start pivot services
cd /opt/pivot-challenge
docker compose up -d 2>/dev/null || docker-compose up -d 2>/dev/null || echo "  ⚠ Docker compose not available — manual start needed"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ Pivot DMZ Setup Complete!"
echo "════════════════════════════════════════════════════════"
echo "  Port Forwards:"
echo "    :8080  → ${HILL3_VPC_IP:-10.x.x.10}:80  (Hill 3 Web)"
echo "    :8443  → ${HILL3_VPC_IP:-10.x.x.10}:443 (Hill 3 HTTPS)"
echo "    :9090  → ${HILL4_VPC_IP:-10.x.x.11}:80  (Hill 4 Web)"
echo "    :5432  → ${HILL4_VPC_IP:-10.x.x.11}:5432(Hill 4 Postgres)"
echo "    :3306  → ${HILL4_VPC_IP:-10.x.x.11}:3306(Hill 4 MySQL)"
echo "    :2210  → ${HILL3_VPC_IP:-10.x.x.10}:22  (Hill 3 SSH)"
echo "    :2211  → ${HILL4_VPC_IP:-10.x.x.11}:22  (Hill 4 SSH)"
echo ""
echo "  Pivot Challenges:"
echo "    SSH Jump: port 2222 (ctfuser:weakpass123)"
echo "    Web:      port 80 (info disclosure)"
echo ""
echo "  Verify: iptables -L -n -t nat"
echo "════════════════════════════════════════════════════════"
