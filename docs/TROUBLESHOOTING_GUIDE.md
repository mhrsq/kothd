# Troubleshooting Guide

> KoTH CTF Platform — Diagnosing and Fixing Common Issues

## Table of Contents

1. [Quick Diagnostic Commands](#1-quick-diagnostic-commands)
2. [Container & Service Issues](#2-container--service-issues)
3. [Database Issues](#3-database-issues)
4. [Redis Issues](#4-redis-issues)
5. [Scoring Engine Issues](#5-scoring-engine-issues)
6. [Scorebot Issues](#6-scorebot-issues)
7. [VPN Issues](#7-vpn-issues)
8. [Hill Server Issues](#8-hill-server-issues)
9. [Web Frontend Issues](#9-web-frontend-issues)
10. [Nginx & Network Issues](#10-nginx--network-issues)

---

## 1. Quick Diagnostic Commands

### Full System Health Check

```bash
# Run from the kothd directory
echo "=== CONTAINERS ===" && docker compose ps && \
echo "=== HEALTH ===" && curl -s localhost:8000/api/health && echo && \
echo "=== GAME STATUS ===" && curl -s localhost:8000/api/admin/game/status \
  -H "X-Admin-Token: $API_ADMIN_TOKEN" && echo && \
echo "=== DISK ===" && df -h / && \
echo "=== MEMORY ===" && free -h && \
echo "=== LOAD ===" && uptime
```

### Quick Service Tests

```bash
# Database
docker exec koth-db pg_isready -U koth_admin -d koth

# Redis
docker exec koth-redis redis-cli -a "$REDIS_PASSWORD" ping

# Scoreboard API
curl -s http://localhost:8000/api/health | jq

# Scorebot
curl -s http://localhost:8081/health | jq

# Nginx
curl -s -o /dev/null -w "%{http_code}" http://localhost/
```

---

## 2. Container & Service Issues

### Container Won't Start

```bash
# Check logs for the failing container
docker compose logs --tail=100 CONTAINER_NAME

# Common containers: scoreboard, scorebot, db, redis, nginx
```

**Common causes:**
- Missing `.env` file or empty `CHANGE_ME` values
- Port conflict (another service using 80, 5432, 6379, etc.)
- Volume permission issues

**Fix:**

```bash
# Verify .env exists and has real values
grep "CHANGE_ME" .env  # Should return nothing

# Check port conflicts
ss -tlnp | grep -E ":(80|5432|6379|8000|8081) "

# Restart with fresh volumes (WARNING: destroys data)
docker compose down -v && docker compose up -d
```

### Container Keeps Restarting

```bash
# Check exit code
docker inspect CONTAINER_NAME --format='{{.State.ExitCode}}'

# Check OOM kills
docker inspect CONTAINER_NAME --format='{{.State.OOMKilled}}'

# If OOM, increase memory limit in docker-compose.yml
```

---

## 3. Database Issues

### Cannot Connect to Database

```bash
# Check if container is running
docker compose ps db

# Test connection from inside the network
docker exec koth-db psql -U koth_admin -d koth -c "SELECT 1;"

# Check logs
docker compose logs --tail=50 db
```

**Common causes:**
- `POSTGRES_PASSWORD` mismatch between `.env` and what was set on first run
- Database not initialized (first run needs `init.sql`)

**Fix for password mismatch:**

```bash
# Nuclear option — recreate database
docker compose down
docker volume rm $(docker volume ls -q | grep koth | grep postgres)
docker compose up -d db
# Wait for initialization, then start the rest
docker compose up -d
```

### Slow Queries

```bash
# Check active queries
docker exec koth-db psql -U koth_admin -d koth -c \
  "SELECT pid, now() - pg_stat_activity.query_start AS duration, query
   FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC;"

# Check table sizes
docker exec koth-db psql -U koth_admin -d koth -c \
  "SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC;"
```

---

## 4. Redis Issues

### Redis Connection Refused

```bash
# Check container
docker compose ps redis

# Test from scoreboard container
docker exec koth-scoreboard redis-cli -h redis -p 6379 -a "$REDIS_PASSWORD" ping

# Check logs
docker compose logs --tail=50 redis
```

**Common causes:**
- `REDIS_PASSWORD` mismatch
- Redis container not ready yet (scoreboard started too early)

### Redis Memory Full

```bash
# Check memory usage
docker exec koth-redis redis-cli -a "$REDIS_PASSWORD" info memory

# Flush non-essential caches (safe during competition)
docker exec koth-redis redis-cli -a "$REDIS_PASSWORD" FLUSHDB
```

---

## 5. Scoring Engine Issues

### Scores Not Updating

1. **Check game state** — Game must be in `running` state:
   ```bash
   curl -s http://localhost:8000/api/admin/game/status \
     -H "X-Admin-Token: $API_ADMIN_TOKEN" | jq .state
   ```

2. **Check tick engine logs**:
   ```bash
   docker compose logs --tail=50 scoreboard | grep -i tick
   ```

3. **Check scorebot reports**:
   ```bash
   docker compose logs --tail=50 scorebot | grep -i "report\|error"
   ```

### Wrong Team Getting Points

- Verify `king.txt` on the hill: `ssh root@HILL_IP 'cat /root/king.txt'`
- Team name in `king.txt` must **exactly match** the registered team name
- Check for trailing whitespace: `ssh root@HILL_IP 'cat -A /root/king.txt'`

---

## 6. Scorebot Issues

### Scorebot Can't SSH to Hills

```bash
# Check scorebot logs
docker compose logs --tail=50 scorebot | grep -i "ssh\|error\|timeout"

# Test SSH manually from scorebot container
docker exec koth-scorebot ssh -o StrictHostKeyChecking=no \
  root@HILL_IP 'cat /root/king.txt'
```

**Common causes:**
- `HILL_SSH_PASS` incorrect in `.env`
- Hill SSH service not running
- Firewall blocking port 22 between scorebot and hill
- SSH host key changed (solved by `StrictHostKeyChecking=no`)

### Scorebot SLA Checks Failing

```bash
# Check SLA endpoint directly
curl -s http://HILL_IP:PORT/health

# For TCP-based SLA checks
nc -zv HILL_IP PORT
```

---

## 7. VPN Issues

### Teams Can't Connect

```bash
# Check WireGuard on VPN server
wg show

# Verify interface is up
ip a show wg0

# Check if forwarding is enabled
sysctl net.ipv4.ip_forward
```

**Common fixes:**
```bash
# Restart WireGuard
systemctl restart wg-quick@wg0

# Enable IP forwarding (if missing)
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.conf && sysctl -p

# Check iptables NAT rules
iptables -t nat -L POSTROUTING -n -v
```

### Teams Connected But Can't Reach Hills

```bash
# Test from the team's perspective
ping HILL_VPC_IP

# Check routing on VPN server
ip route

# Verify hill is reachable from VPN server
ssh root@VPN_IP "ping -c 2 HILL_VPC_IP"
```

---

## 8. Hill Server Issues

### Hill Not Responding

```bash
# Ping the hill
ping HILL_IP

# Check Docker on the hill
ssh root@HILL_IP 'docker compose ps'

# Restart hill services
ssh root@HILL_IP 'cd /opt/hill && docker compose restart'
```

### king.txt Permission Issues

```bash
# Ensure king.txt is writable
ssh root@HILL_IP 'ls -la /root/king.txt'

# Fix permissions
ssh root@HILL_IP 'chmod 666 /root/king.txt'
```

### Hill Agent Not Reporting

```bash
# Check agent status
ssh root@HILL_IP 'systemctl status koth-agent'

# Check agent logs
ssh root@HILL_IP 'journalctl -u koth-agent --tail=50'

# Restart agent
ssh root@HILL_IP 'systemctl restart koth-agent'
```

---

## 9. Web Frontend Issues

### Scoreboard Not Loading

1. Check browser console for errors (F12 → Console)
2. Verify API is responding: `curl http://YOUR_SERVER/api/health`
3. Check WebSocket connection: look for WS errors in browser console

### Admin Panel Auth Fails

- Ensure you're using the correct `API_ADMIN_TOKEN` from `.env`
- Token is case-sensitive
- Check for extra whitespace when copying

### WebSocket Disconnects

```bash
# Check nginx WebSocket config
grep -A5 "websocket\|upgrade" nginx/nginx.conf

# Check scoreboard WS logs
docker compose logs --tail=50 scoreboard | grep -i "websocket\|ws"
```

---

## 10. Nginx & Network Issues

### 502 Bad Gateway

```bash
# Check if upstream (scoreboard) is running
docker compose ps scoreboard

# Check nginx logs
docker compose logs --tail=50 nginx

# Verify nginx can reach scoreboard
docker exec koth-nginx curl -s http://scoreboard:8000/api/health
```

### SSL / HTTPS Issues

If you've added SSL, check:
```bash
# Certificate validity
openssl s_client -connect YOUR_SERVER:443 -servername YOUR_SERVER

# Nginx config test
docker exec koth-nginx nginx -t
```

### Connection Timeouts

```bash
# Check firewall
iptables -L -n
ufw status

# Check if server is listening
ss -tlnp | grep -E ":(80|443) "

# Check DNS resolution (if using domain)
dig YOUR_DOMAIN
```

---

## General Tips

- **Always check logs first**: `docker compose logs --tail=100 CONTAINER_NAME`
- **Use `jq` for API responses**: `curl ... | jq`
- **Database backups before changes**: `docker exec koth-db pg_dump -U koth_admin koth > backup.sql`
- **The Organizer Dashboard** (`/organizer.html`) has a built-in troubleshooting section with clickable commands
