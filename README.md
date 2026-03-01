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

### Option A: One-Command Server Deploy

```bash
# From a fresh Ubuntu/Debian server (as root):
curl -fsSL https://raw.githubusercontent.com/mhrsq/kothd/main/scripts/deploy.sh | bash
```

Or via SSH:

```bash
ssh root@YOUR_SERVER 'bash -s' < scripts/deploy.sh
```

This clones the repo, installs Docker, generates a secure `.env`, builds images, and starts all services.

### Option B: Manual Setup

```bash
git clone https://github.com/mhrsq/kothd.git
cd kothd

# Generate secure .env with random passwords
bash scripts/generate-env.sh

# Build and start
docker compose up -d
```

### Verify Deployment

```bash
bash scripts/smoke-test.sh
```

This checks all containers, database, Redis, API endpoints, and `.env` security.

### Access

| URL | Description |
|-----|-------------|
| `http://YOUR_SERVER` | Scoreboard (public) |
| `http://YOUR_SERVER/admin.html` | Admin panel |
| `http://YOUR_SERVER/organizer.html` | Organizer dashboard |
| `http://YOUR_SERVER/dashboard.html` | Participant dashboard |

### Register Teams

Via admin panel or API:

```bash
curl -X POST http://YOUR_SERVER/api/teams/bulk \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "teams": [
      {"name": "team-alpha", "category": "default"},
      {"name": "team-bravo", "category": "default"}
    ]
  }'
```

### Start Game

```bash
curl -X POST http://YOUR_SERVER/api/admin/game/control \
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
├── scripts/              # Deployment & automation scripts
│   ├── deploy.sh         # One-command server deployment
│   ├── generate-env.sh   # Secure .env generator
│   ├── smoke-test.sh     # Post-deploy health checks
├── docs/                 # Documentation
├── docker-compose.yml    # Main platform deployment
├── .env.example          # Configuration template
└── LICENSE               # MIT License
```

## Deployment

### Scripts

| Script | Description |
|--------|-------------|
| `scripts/deploy.sh` | Full server deployment (Docker install, clone, env gen, build, start) |
| `scripts/generate-env.sh` | Generate `.env` with cryptographically random passwords |
| `scripts/smoke-test.sh` | Post-deployment health check (containers, DB, Redis, API, config) |

### Docker Security

The platform includes production-grade Docker hardening:

- **Non-root containers** — All services run as unprivileged `koth` user
- **Resource limits** — Memory and CPU constraints on every container
- **No-new-privileges** — Prevents privilege escalation inside containers
- **Read-only mounts** — Application code and config mounted as read-only
- **tmpfs** — Nginx temp/cache uses memory-backed filesystem
- **Redis memory cap** — `maxmemory 256mb` with LRU eviction policy

### Server Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 2 GB | 4 GB |
| Disk | 10 GB | 20 GB |
| OS | Ubuntu 22.04+ / Debian 12+ | Ubuntu 24.04 |
| Ports | 80 (HTTP) | 80, 443 (HTTPS) |

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

## Development

### Prerequisites

- Python ≥ 3.11
- Go ≥ 1.22
- Docker & Docker Compose v2

### Run Tests

```bash
# All tests (Python + Go)
make test

# Python tests only
make test-py

# Go tests only
make test-go

# Python tests with HTML coverage report
make test-cov
```

### Lint & Format

```bash
make lint    # ruff check + go vet
make fmt     # ruff format + gofmt
```

### Test Coverage

| Module | Coverage |
|--------|----------|
| `services/scoring.py` | 97% |
| `config.py` | 94% |
| `routers/auth.py` | 82% |
| `services/game_manager.py` | 67% |
| Overall | ~44% |

### CI/CD

GitHub Actions runs on every push/PR to `main`:

1. **Python Tests** — pytest with coverage (Python 3.12)
2. **Python Lint** — ruff check
3. **Go Tests** — go test with race detector (Go 1.22)
4. **Docker Build** — builds all 3 container images

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make test` | Run all tests (Python + Go) |
| `make test-cov` | Python tests with HTML coverage |
| `make lint` | Lint all code |
| `make fmt` | Auto-format all code |
| `make build` | Build Docker images |
| `make up` | Start all containers |
| `make down` | Stop all containers |
| `make clean` | Remove build artifacts |

## Documentation

- [Admin Guide](docs/admin-guide.md) — Operator manual for running a competition
- [Troubleshooting Guide](docs/TROUBLESHOOTING_GUIDE.md) — Diagnosing and fixing common issues
- [Migration Guide](docs/MIGRATION_GUIDE_ON_PREMISE.md) — Deploying to on-premise infrastructure
- [Hill Challenges](hills/README-CHALLENGES.md) — Challenge descriptions and vulnerability details

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE) — Copyright (c) 2026 mhrsq
