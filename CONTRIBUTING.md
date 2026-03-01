# Contributing to kothd

Thanks for your interest in contributing! Here's how you can help.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/kothd.git`
3. Create a branch: `git checkout -b feature/your-feature`
4. Make your changes
5. Test locally with `docker compose up -d`
6. Commit and push
7. Open a Pull Request

## Development Setup

```bash
cp .env.example .env
# Edit .env with development values
docker compose up -d
```

The scoreboard API runs on `:8000`, scorebot on `:8081`, and nginx on `:80`.

## What to Work On

- **Bug fixes** — Check the Issues tab
- **New hill challenges** — Add challenge containers under `hills/`
- **Documentation** — Improve guides, add examples
- **Frontend** — Improve the scoreboard, admin panel, or dashboard UX
- **Internationalization** — Help translate the UI (currently has some Indonesian text)
- **Testing** — Add automated tests for the API and scoring engine

## Code Style

- **Python**: Follow PEP 8, use type hints
- **Go**: Run `gofmt` before committing
- **HTML/JS/CSS**: Keep inline — the frontend is single-file for easy deployment
- **Commits**: Use clear, descriptive commit messages

## Adding a Hill Challenge

1. Create `hills/hillN-name/` with:
   - `Dockerfile` — Sets up the vulnerable environment
   - `docker-compose.yml` — Container configuration
   - `entrypoint.sh` — Service initialization
2. Ensure SSH is available for scorebot king.txt checks
3. Include an SLA health endpoint
4. Add documentation to `hills/README-CHALLENGES.md`

## Reporting Issues

- Use GitHub Issues
- Include steps to reproduce
- Include relevant logs (`docker compose logs CONTAINER`)

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
