# Admin / Operator Guide

> KoTH CTF Platform — Competition Administration Manual

## Table of Contents

1. [Pre-Competition Setup](#pre-competition-setup)
2. [Day-of-Event Operations](#day-of-event-operations)
3. [During Competition](#during-competition)
4. [Emergency Procedures](#emergency-procedures)
5. [Post-Competition](#post-competition)

---

## Pre-Competition Setup

### D-7: Infrastructure Deployment

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — set all CHANGE_ME values

# 2. Deploy the platform
docker compose up -d

# 3. Verify all containers are healthy
docker compose ps

# 4. Deploy hills
./hills/deploy-all.sh
```

### D-3: Team Registration

#### Via Admin Panel

1. Navigate to `http://YOUR_SERVER/admin.html`
2. Enter your admin token (from `.env` → `API_ADMIN_TOKEN`)
3. Use the "Register Team" section to add teams individually

#### Via API (Bulk Registration)

```bash
curl -X POST http://YOUR_SERVER/api/teams/bulk \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": [
      {"name": "team-1", "category": "default"},
      {"name": "team-2", "category": "default"},
      {"name": "team-3", "category": "default"}
    ]
  }'
```

> **Tip**: Use the `category` field to group teams (e.g., `"pro"`, `"student"`). The default category is `"default"`.

### D-1: Final Checks

```bash
# 1. Write a test king on Hill 1
ssh root@YOUR_HILL1_IP 'echo "team-1" > /root/king.txt'

# 2. Start game in test mode
curl -X POST http://YOUR_SERVER/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'

# 3. Wait 60 seconds (one tick), then check scoreboard
curl http://YOUR_SERVER/api/scoreboard | jq

# 4. Stop game
curl -X POST http://YOUR_SERVER/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "stop"}'

# 5. Reset all game data
curl -X POST http://YOUR_SERVER/api/admin/game/reset \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"

# 6. Reset king files on all hills
ssh root@YOUR_HILL1_IP 'echo "nobody" > /root/king.txt'
ssh root@YOUR_HILL2_IP 'echo "nobody" > /root/king.txt'
```

---

## Day-of-Event Operations

### Sample Timeline

| Relative Time | Action |
|---------------|--------|
| T-2h | Operator arrives, verify all servers UP |
| T-1.5h | Run health checks on all containers |
| T-1h | Distribute VPN configs to team stations |
| T-45m | Teams connect VPN, verify connectivity |
| T-30m | Brief teams on rules (king.txt, SLA, scoring) |
| T-15m | Open scoreboard on projector display |
| **T=0** | **START GAME** |
| T+5m | First tick — scoring begins |
| T-30m before end | Freeze scoreboard (optional) |
| **T=end** | **GAME ENDS** |
| T+15m | Reveal final scores |
| T+30m | Awards ceremony |

### Starting the Game

```bash
# Via Admin Panel — Click "Start Game" button
# Or via API:
curl -X POST http://YOUR_SERVER/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'
```

### VPN Distribution

Each team receives:
- WireGuard config file: `team-XX.conf`
- VPN IP assignment: `10.10.0.(team# + 1)`

---

## During Competition

### Monitoring

| Resource | URL |
|----------|-----|
| Live Scoreboard | `http://YOUR_SERVER` |
| Admin Panel | `http://YOUR_SERVER/admin.html` |
| Organizer Console | `http://YOUR_SERVER/organizer.html` |
| Participant Dashboard | `http://YOUR_SERVER/dashboard.html` |

### Common Admin Actions

#### Pause Game (Emergency)

```bash
curl -X POST http://YOUR_SERVER/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "pause"}'
```

#### Resume Game

```bash
curl -X POST http://YOUR_SERVER/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "resume"}'
```

#### Adjust Score (Manual Bonus/Penalty)

```bash
curl -X POST http://YOUR_SERVER/api/admin/score/adjust \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": 1,
    "points": -50,
    "reason": "Penalty: DDoS attack detected"
  }'
```

#### Check Game Status

```bash
curl http://YOUR_SERVER/api/admin/game/status \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" | jq
```

#### Freeze Scoreboard

```bash
curl -X POST http://YOUR_SERVER/api/admin/scoreboard/freeze \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"frozen": true}'
```

#### Send Announcement

```bash
curl -X POST http://YOUR_SERVER/api/admin/announce \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "30 minutes remaining!", "type": "warning"}'
```

#### View Audit Log

```bash
curl http://YOUR_SERVER/api/admin/audit \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" | jq
```

### Service Health Monitoring

```bash
# Check all containers
docker compose ps

# Check scoreboard logs
docker compose logs --tail=50 scoreboard

# Check scorebot logs
docker compose logs --tail=50 scorebot

# Check hill king.txt
ssh root@YOUR_HILL1_IP 'cat /root/king.txt'
ssh root@YOUR_HILL2_IP 'cat /root/king.txt'
```

---

## Emergency Procedures

### Scoreboard Down

```bash
# Restart scoreboard only
docker compose restart scoreboard

# If database issue
docker compose restart db scoreboard

# Nuclear option — restart everything
docker compose down && docker compose up -d
```

### Hill Server Unresponsive

```bash
# Check connectivity
ping YOUR_HILL1_IP
ping YOUR_HILL2_IP

# Force restart Docker on hill
ssh root@YOUR_HILL1_IP 'cd /opt/hill && docker compose restart'
```

### VPN Issues

```bash
# Check WireGuard status on VPN server
ssh root@YOUR_VPN_IP 'wg show'

# Restart WireGuard
ssh root@YOUR_VPN_IP 'systemctl restart wg-quick@wg0'
```

### Database Backup During Competition

```bash
# Backup
docker exec koth-db pg_dump -U koth_admin koth > backup.sql

# Restore
cat backup.sql | docker exec -i koth-db psql -U koth_admin koth
```

---

## Post-Competition

### Export Results

```bash
# Final leaderboard
curl http://YOUR_SERVER/api/scoreboard/leaderboard | jq > final-results.json

# All tick data
curl http://YOUR_SERVER/api/scoreboard/ticks?limit=1000 | jq > all-ticks.json

# First bloods
curl http://YOUR_SERVER/api/scoreboard/first-bloods | jq > first-bloods.json

# Full database dump
docker exec koth-db pg_dump -U koth_admin koth > full-dump.sql
```

### Shutdown

```bash
# Stop game
curl -X POST http://YOUR_SERVER/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "stop"}'

# Stop all services (keep data)
docker compose stop

# Full cleanup (destroys data!)
docker compose down -v
```
