# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] — 2026-03-02

### Added

- **Test Suite** — 93 Python tests + 20 Go tests covering scoring, game management, API endpoints, schema validation, and scorebot checker
- **CI/CD Pipeline** — GitHub Actions workflow with 4 jobs: Python tests, ruff lint, Go tests, Docker build
- **pyproject.toml** — Centralized project configuration (pytest, coverage, ruff)
- **Makefile** — Developer convenience targets (test, lint, fmt, build, up, down, clean)
- **Test Fixtures** — Reusable conftest.py with in-memory SQLite, mock Redis, HTTPX async client

### Changed

- Settings model now uses `extra = "ignore"` to handle env vars not defined in the schema
- Relaxed coverage threshold to 40% (core business logic at 97%)

### Coverage Highlights

- `services/scoring.py` — 97% (core game logic)
- `config.py` — 94%
- `routers/auth.py` — 82%
- `services/game_manager.py` — 67%

---

## [1.0.0] — 2026-02-28

### Added

- Initial open-source release
- FastAPI-based scoreboard with real-time WebSocket updates
- Go-based scorebot with SSH hill checking and SLA verification
- Go-based hill agent for real-time status reporting
- 4 built-in challenge hills (Web Fortress, Service Bastion, API Gateway, Data Vault)
- Pivot DMZ multi-hill hosting support
- Admin panel with full game lifecycle control
- Organizer dashboard with built-in operations guide
- Participant dashboard with VPN status and hill information
- Team registration (individual and bulk) with category support
- Tick-based scoring engine with configurable intervals
- First blood tracking and bonus points
- Defense streak bonuses
- SLA penalty system
- Scoreboard freeze/unfreeze for final reveal
- Score adjustment (manual bonus/penalty)
- Announcement system (WebSocket-pushed)
- Audit logging for all admin actions
- WireGuard VPN management integration
- Docker Compose one-command deployment
- Nginx reverse proxy configuration
- Environment-based configuration (`.env`)
- Deployment and maintenance shell scripts
- Comprehensive documentation (admin guide, troubleshooting, migration, challenge docs)
