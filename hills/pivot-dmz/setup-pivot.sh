#!/bin/bash
# Setup script for Pivot DMZ server
# Adds secondary IPs and deploys Hill 3 + Hill 4 containers

set -e

echo "=== Pivot DMZ Setup ==="

# Add secondary IPs for Hill 3 and Hill 4 (if not already added)
if ! ip addr show eth1 | grep -q "${HILL3_VPC_IP:-10.x.x.10}"; then
    echo "[*] Adding IP ${HILL3_VPC_IP:-10.x.x.10} for Hill 3..."
    ip addr add ${HILL3_VPC_IP:-10.x.x.10}/20 dev eth1
else
    echo "[*] IP ${HILL3_VPC_IP:-10.x.x.10} already configured"
fi

if ! ip addr show eth1 | grep -q "${HILL4_VPC_IP:-10.x.x.11}"; then
    echo "[*] Adding IP ${HILL4_VPC_IP:-10.x.x.11} for Hill 4..."
    ip addr add ${HILL4_VPC_IP:-10.x.x.11}/20 dev eth1
else
    echo "[*] IP ${HILL4_VPC_IP:-10.x.x.11} already configured"
fi

# Make IPs persistent via netplan
if ! grep -q "${HILL3_VPC_IP:-10.x.x.10}" /etc/netplan/*.yaml 2>/dev/null; then
    echo "[*] Making IPs persistent in netplan..."
    # Backup existing netplan
    cp /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak 2>/dev/null || true
    
    # Add secondary IPs to eth1 config
    sed -i '/set-name: "eth1"/a\      routes: []\n' /etc/netplan/50-cloud-init.yaml 2>/dev/null || true
    
    # Create override netplan for additional IPs
    cat > /etc/netplan/60-hill-ips.yaml << 'EOF'
network:
  version: 2
  ethernets:
    eth1:
      addresses:
        - "${HILL3_VPC_IP:-10.x.x.10}/20"
        - "${HILL4_VPC_IP:-10.x.x.11}/20"
EOF
    echo "[*] Netplan config created"
fi

# Create king.txt files
echo "[*] Creating king.txt files..."
echo 'nobody' > /root/king.txt
chmod 644 /root/king.txt

echo "[*] Setup complete! IPs configured:"
ip addr show eth1 | grep "inet "

echo ""
echo "[*] Now run: cd /opt/hill-challenge && docker compose up -d --build"
