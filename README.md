# kothd — King of the Hill CTF Platform

A production-ready **King of the Hill** (KoTH) CTF engine built for live competitions. Includes real-time scoring, automated hill checking, WebSocket-powered live scoreboard, participant VPN management, and a full admin/organizer dashboard.

## Features

- **Real-time Scoring** — Tick-based engine checks hill ownership every 60 s (configurable) and awards points automatically
- **4 Built-in Hills** — Web Fortress, Service Bastion, API Gateway, Data Vault — each with realistic vulnerabilities and privesc chains
- **Scorebot** — Go-based checker SSHes into hills, reads `king.txt`, verifies SLA, and reports results
- **Hill Agent** — Optional Go agent installed on hills for real-time status reporting via WebSocket
- **Live Scoreboard** — WebSocket-powered dashboard with animations, first-blood tracking, and category filtering
- **Admin Panel** — Full game lifecycle control (start/pause/resume/stop/reset), team management, score adjustments, announcements, audit log
- **Organizer Dashboard** — Comprehensive operations console with built-in guide, deploy wizards, and SSH quick-access
- **VPN Management** — WireGuard config generation and distribution through the platform
- **Pivot DMZ** — Multi-hill hosting on a single server with port-based routing
- **Docker Compose** — One-command deployment for the entire platform

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  KoTH Server                     │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Scoreboard│  │ Scorebot │  │  Nginx   │      │
│  │ (FastAPI) │  │   (Go)   │  │ (Reverse │      │
│  │  :8000    │  │  :8081   │  │  Proxy)  │      │
│  └─────┬─────┘  └────┬─────┘  └──────────┘      │
│        │              │                           │
│  ┌─────┴─────┐  ┌────┴─────┐                     │
│  │ PostgreSQL│  │  Redis   │                     │
│  │   :5432   │  │  :6379   │                     │
│  └───────────┘  └──────────┘                     │
└─────────────────────────────────────────────────┘
        │ SSH :22                │ WebSocket
        ▼                       ▼
  ┌───────────┐           ┌───────────┐
  │  Hill 1   │           │  Hill 2   │
  │  (Web)    │           │ (Service) │
  └───────────┘           └───────────┘
  ┌───────────────────────────────┐
  │         Pivot DMZ             │
  │  Hill 3 (:8080/:2210)        │
  │  Hill 4 (:27017/:2211)       │
  └───────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Scoreboard API | Python 3.12, FastAPI, SQLAlchemy, Pydantic |
| Scorebot | Go 1.22, Gin, SSH client |
| Hill Agent | Go 1.22, Gin, WebSocket |
| Database | PostgreSQL 16 |
| Cache / PubSub | Redis 7 |
| Reverse Proxy | Nginx |
| VPN | WireGuard |
| Containerization | Docker & Docker Compose |

## Quick Start

### Prerequisites

- Docker & Docker Compose v2
- Git

### 1. Clone & Configure

```bash
git clone https://github.com/mhrsq/kothd.git
cd kothd
cp .env.example .env
# Edit .env — fill in all CHANGE_ME values
```

### 2. Deploy

```bash
docker compose up -d
```

This starts 5 containers: `scoreboard`, `scorebot`, `nginx`, `db`, `redis`.

### 3. Access

| URL | Description |
|-----|-------------|
| `http://localhost` | Scoreboard (public) |
| `http://localhost/admin.html` | Admin panel |
| `http://localhost/organizer.html` | Organizer dashboard |
| `http://localhost/dashboard.html` | Participant dashboard |

### 4. Register Teams

Via admin panel or API:

```bash
curl -X POST http://localhost/api/teams/bulk \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": [
      {"name": "team-alpha", "category": "default"},
      {"name": "team-bravo", "category": "default"}
    ]
  }'
```

### 5. Start Game

```bash
curl -X POST http://localhost/api/admin/game/control \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'
```

## Hill Setup

Each hill is a Docker container with intentional vulnerabilities. Players exploit them to gain root and write their team name to `/root/king.txt`.

See [hills/README-CHALLENGES.md](hills/README-CHALLENGES.md) for challenge details.

### Deploy Hills

```bash
# Deploy individual hill
cd hills/hill1-web && docker compose up -d

# Or deploy all hills at once
./hills/deploy-all.sh
```

### Hill Agent (Optional)

Install on each hill for real-time status reporting:

```bash
cd hill-agent
./deploy.sh --server http://YOUR_KOTH_SERVER:8000 --hill-id 1
```

## Project Structure

```
kothd/
├── scoreboard/           # FastAPI scoreboard + API
│   ├── app/
│   │   ├── config.py     # Environment-based configuration
│   │   ├── main.py       # FastAPI application entry
│   │   ├── models.py     # SQLAlchemy ORM models
│   │   ├── schemas.py    # Pydantic request/response schemas
│   │   ├── database.py   # Database session management
│   │   ├── routers/      # API route handlers
│   │   └── services/     # Business logic (scoring, ticks, game, VPN)
│   ├── static/           # Frontend (HTML/CSS/JS)
│   ├── init.sql          # Database initialization
│   ├── Dockerfile
│   └── requirements.txt
├── scorebot/             # Go-based hill checker
│   ├── main.go           # Scorebot entry point
│   ├── checker/          # SSH checker logic
│   └── Dockerfile
├── hill-agent/           # Optional Go agent for hills
│   ├── main.go
│   ├── deploy.sh         # One-command hill agent deployment
│   └── Dockerfile
├── hills/                # Challenge hill definitions
│   ├── hill1-web/        # Web Fortress (SQLi, upload, RCE)
│   ├── hill2-services/   # Service Bastion (FTP, TCP, privesc)
│   ├── hill3-api/        # API Gateway (auth bypass, SSRF)
│   ├── hill4-db/         # Data Vault (NoSQL injection, Redis)
│   └── pivot-dmz/        # Multi-hill host config
├── nginx/                # Reverse proxy configuration
├── scripts/              # Deployment & maintenance scripts
├── docs/                 # Documentation
├── docker-compose.yml    # Main platform deployment
├── .env.example          # Configuration template
└── LICENSE               # MIT License
```

## Configuration

All configuration is via environment variables. See [.env.example](.env.example) for the full list.

Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | Database password | *(required)* |
| `REDIS_PASSWORD` | Redis password | *(required)* |
| `API_SECRET_KEY` | API signing key | *(required)* |
| `API_ADMIN_TOKEN` | Admin API token | *(required)* |
| `TICK_INTERVAL` | Seconds between scoring ticks | `60` |
| `GAME_DURATION_HOURS` | Competition length in hours | `6` |
| `HILL_SSH_PASS` | SSH password for hill access | *(required)* |
| `REGISTRATION_CODE` | Team self-registration code | *(required)* |
| `EVENT_NAME` | Displayed event name | `KoTH CTF` |

## API Overview

All admin endpoints require the `X-Admin-Token` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/admin/game/control` | Start / pause / resume / stop game |
| `POST` | `/api/admin/game/reset` | Reset all game data |
| `GET` | `/api/admin/game/status` | Current game state |
| `POST` | `/api/teams/bulk` | Bulk register teams |
| `GET` | `/api/scoreboard` | Live scoreboard data |
| `GET` | `/api/scoreboard/leaderboard` | Final leaderboard |
| `GET` | `/api/scoreboard/first-bloods` | First blood records |
| `POST` | `/api/admin/score/adjust` | Manual score adjustment |
| `POST` | `/api/admin/announce` | Send announcement |
| `GET` | `/api/admin/audit` | Audit log |
| `POST` | `/api/admin/hills` | Add/modify hills |
| `POST` | `/api/admin/scoreboard/freeze` | Freeze scoreboard |

See the built-in Organizer Guide (`/organizer.html`) for the complete API reference.

## Documentation

- [Admin Guide](docs/admin-guide.md) — Operator manual for running a competition
- [Troubleshooting Guide](docs/TROUBLESHOOTING_GUIDE.md) — Diagnosing and fixing common issues
- [Migration Guide](docs/MIGRATION_GUIDE_ON_PREMISE.md) — Deploying to on-premise infrastructure
- [Hill Challenges](hills/README-CHALLENGES.md) — Challenge descriptions and vulnerability details

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE) — Copyright (c) 2026 mhrsq
