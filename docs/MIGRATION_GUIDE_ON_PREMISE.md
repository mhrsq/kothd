# Migration Guide: Cloud → On-Premise

> KoTH CTF Platform — Deploying to On-Premise Infrastructure

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Hardware Requirements](#2-hardware-requirements)
3. [Topology Options](#3-topology-options)
4. [Network Configuration](#4-network-configuration)
5. [Step-by-Step Deployment](#5-step-by-step-deployment)
6. [WireGuard VPN Setup](#6-wireguard-vpn-setup)
7. [Validation Checklist](#7-validation-checklist)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Architecture Overview

The platform requires these components:

| Role | Description | Services |
|------|-------------|----------|
| **KoTH Server** | Main platform | Scoreboard + Scorebot + DB + Redis + Nginx |
| **Hill 1** | Web Fortress | Docker container with web app |
| **Hill 2** | Service Bastion | Docker container with TCP/FTP services |
| **Pivot DMZ** | Multi-hill host | Hill 3 (API Gateway) + Hill 4 (Data Vault) |
| **VPN Server** | Participant access | WireGuard VPN |

> **Note**: The VPN server can run on the KoTH server if you have a single-server setup.

---

## 2. Hardware Requirements

### Recommended (Multi-Server)

| Role | CPU | RAM | Disk | Network |
|------|-----|-----|------|---------|
| KoTH Server | 4 cores | 8 GB | 50 GB SSD | 1 Gbps |
| Each Hill | 2 cores | 4 GB | 20 GB SSD | 1 Gbps |
| Pivot DMZ | 4 cores | 8 GB | 40 GB SSD | 1 Gbps |
| VPN Server | 2 cores | 2 GB | 10 GB SSD | 1 Gbps |

### Minimum (Single Server)

If running everything on one machine (for testing or small events):

| Component | Requirement |
|-----------|-------------|
| CPU | 8 cores |
| RAM | 16 GB |
| Disk | 100 GB SSD |
| Network | 1 Gbps, 2+ NICs recommended |

### Software Requirements

- Ubuntu 22.04+ or Debian 12+
- Docker Engine 24+ & Docker Compose v2
- WireGuard (for VPN)
- Git

---

## 3. Topology Options

### Option A: Fully Segmented (Recommended)

```
                    [Internet/LAN]
                         │
                    [Firewall/Router]
                         │
              ┌──────────┼──────────┐
              │          │          │
         [VPN Server] [KoTH Server] │
         10.10.0.1    10.0.1.10    │
              │          │          │
              └──────────┼──────────┘
                         │
                   [Hill Network]
                   10.0.1.0/24
              ┌──────┼──────┐
              │      │      │
          [Hill 1] [Hill 2] [Pivot DMZ]
          10.0.1.2 10.0.1.3 10.0.1.4
```

- Separate VLANs for management and hill networks
- Firewall rules between segments
- Most secure option

### Option B: Flat Network (Simple)

```
         [All servers on same subnet]
              10.0.1.0/24
    ┌────┬────┬────┬────┬────┐
  KoTH  H1   H2  Pivot  VPN
  .10   .2   .3   .4    .5
```

- All servers on one subnet
- Simpler setup, less isolation
- Suitable for small/trusted events

### Option C: Single Server

```
    [Single Server — 10.0.1.10]
    ├── Docker: scoreboard, scorebot, nginx, db, redis
    ├── Docker: hill1, hill2
    ├── Docker: hill3-api, hill4-db (pivot)
    └── WireGuard: wg0
```

- Everything in Docker on one machine
- Easiest to set up
- Limited to small events (≤10 teams)

---

## 4. Network Configuration

### IP Assignments

Create a network plan before deploying. Example:

| Server | IP | Purpose |
|--------|----|---------|
| KoTH Server | 10.0.1.10 | Scoreboard, Scorebot, DB, Redis, Nginx |
| Hill 1 | 10.0.1.2 | Web Fortress |
| Hill 2 | 10.0.1.3 | Service Bastion |
| Pivot DMZ | 10.0.1.4 | Hill 3 (:8080/:2210) + Hill 4 (:27017/:2211) |
| VPN Server | 10.0.1.5 | WireGuard (participant subnet: 10.10.0.0/24) |

### Firewall Rules

Minimum required rules:

| Source | Destination | Port | Purpose |
|--------|-------------|------|---------|
| VPN clients | KoTH Server | 80 | Scoreboard web access |
| VPN clients | Hills | 22, 80, 8080, 9999, 27017 | Challenge access |
| KoTH (Scorebot) | Hills | 22 | King.txt checks |
| KoTH (Scorebot) | Hills | 80, 8080, 9999, 27017 | SLA checks |
| Hills (Agent) | KoTH Server | 8000 | Agent reporting |
| Internet | VPN Server | 51820/udp | WireGuard |
| Internet | KoTH Server | 80/443 | Public scoreboard (optional) |

---

## 5. Step-by-Step Deployment

### 5.1. Prepare All Servers

On each server:

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# Install Docker Compose plugin
apt install -y docker-compose-plugin

# Verify
docker compose version
```

### 5.2. Deploy KoTH Server

```bash
# Clone the repository
git clone https://github.com/mhrsq/kothd.git /opt/koth
cd /opt/koth

# Configure
cp .env.example .env
nano .env  # Set all values — especially IPs, passwords, tokens

# Start the platform
docker compose up -d

# Verify
docker compose ps
curl http://localhost/api/health
```

### 5.3. Deploy Hills

```bash
# On the KoTH server, update hill configuration in the database
# Add your hills via admin API:
curl -X POST http://localhost/api/admin/hills \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Web Fortress",
    "ip": "10.0.1.2",
    "ssh_port": 22,
    "sla_url": "http://10.0.1.2:80/health",
    "points": 10
  }'
```

On each hill server:

```bash
# Copy hill files
scp -r hills/hill1-web root@10.0.1.2:/opt/hill/
ssh root@10.0.1.2 'cd /opt/hill && docker compose up -d'
```

Or use the deploy scripts:

```bash
# Edit deploy scripts to set your IPs
nano hills/deploy-all.sh
./hills/deploy-all.sh
```

### 5.4. Deploy Hill Agent (Optional)

On each hill:

```bash
scp hill-agent/deploy.sh root@HILL_IP:/tmp/
ssh root@HILL_IP 'bash /tmp/deploy.sh --server http://KOTH_SERVER_IP:8000 --hill-id 1'
```

### 5.5. Deploy VPN Server

```bash
# Install WireGuard
apt install -y wireguard

# Generate server keys
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

# Create config
cat > /etc/wireguard/wg0.conf << 'EOF'
[Interface]
Address = 10.10.0.1/24
ListenPort = 51820
PrivateKey = SERVER_PRIVATE_KEY

# Enable forwarding
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
EOF

# Add route to hill network
PostUp = ip route add 10.0.1.0/24 via GATEWAY_IP

# Enable IP forwarding
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.conf
sysctl -p

# Start WireGuard
systemctl enable --now wg-quick@wg0
```

Generate team configs via the platform's VPN management API or manually.

---

## 6. WireGuard VPN Setup

### Generate Team Configs

For each team:

```bash
# Generate team keys
wg genkey | tee team-N_private.key | wg pubkey > team-N_public.key

# Add peer to server config
cat >> /etc/wireguard/wg0.conf << EOF

[Peer]
PublicKey = $(cat team-N_public.key)
AllowedIPs = 10.10.0.$((N + 1))/32
EOF

# Create team config file
cat > team-N.conf << EOF
[Interface]
PrivateKey = $(cat team-N_private.key)
Address = 10.10.0.$((N + 1))/24
DNS = 8.8.8.8

[Peer]
PublicKey = $(cat /etc/wireguard/server_public.key)
Endpoint = VPN_PUBLIC_IP:51820
AllowedIPs = 10.0.1.0/24, 10.10.0.0/24
PersistentKeepalive = 25
EOF
```

### Apply Changes

```bash
# Reload WireGuard without disconnecting existing clients
wg syncconf wg0 <(wg-quick strip wg0)
```

---

## 7. Validation Checklist

Run through this checklist after deployment:

### Infrastructure

- [ ] All Docker containers running (`docker compose ps` on each server)
- [ ] KoTH API responds: `curl http://KOTH_IP/api/health`
- [ ] Scorebot health: `curl http://KOTH_IP:8081/health`
- [ ] Database accessible: `docker exec koth-db pg_isready`
- [ ] Redis accessible: `docker exec koth-redis redis-cli ping`

### Hills

- [ ] Hill 1 SSH working: `ssh root@HILL1_IP 'cat /root/king.txt'`
- [ ] Hill 2 SSH working: `ssh root@HILL2_IP 'cat /root/king.txt'`
- [ ] Hill 3 SSH working: `ssh -p 2210 root@PIVOT_IP 'cat /root/king.txt'`
- [ ] Hill 4 SSH working: `ssh -p 2211 root@PIVOT_IP 'cat /root/king.txt'`
- [ ] SLA endpoints responding for all hills

### VPN

- [ ] WireGuard running: `wg show`
- [ ] Test client connects successfully
- [ ] Test client can reach scoreboard
- [ ] Test client can reach hills
- [ ] Test client can SSH to hills

### Scoring

- [ ] Register a test team
- [ ] Write test team name to king.txt on a hill
- [ ] Start game, wait one tick
- [ ] Verify points appear on scoreboard
- [ ] Stop and reset game

---

## 8. Troubleshooting

### Scorebot Can't Reach Hills

```bash
# From the KoTH server, test connectivity
docker exec koth-scorebot ping -c 2 HILL_IP

# If using Docker, ensure scorebot has network access to hill IPs
# You may need to use host networking or add routes
```

### VPN Clients Can't Reach Hills

```bash
# Check routing on VPN server
ip route | grep 10.0.1

# Add missing route
ip route add 10.0.1.0/24 via GATEWAY_IP

# Check forwarding
sysctl net.ipv4.ip_forward  # Must be 1

# Check iptables
iptables -L FORWARD -n -v
```

### Performance Issues

```bash
# Monitor resources
htop
docker stats

# Check disk I/O
iostat -x 1

# If database is slow, check connection count
docker exec koth-db psql -U koth_admin -d koth -c "SELECT count(*) FROM pg_stat_activity;"
```

For more troubleshooting, see [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md).
