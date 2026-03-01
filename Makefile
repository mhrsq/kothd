.PHONY: help test test-py test-go test-cov lint lint-py lint-go fmt build up down logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Testing ──────────────────────────────────────────────────────────────────

test: test-py test-go ## Run all tests

test-py: ## Run Python tests
	PYTHONPATH=scoreboard python -m pytest tests/ -v --tb=short

test-go: ## Run Go tests
	cd scorebot && go test -v -race ./...

test-cov: ## Run Python tests with coverage report
	PYTHONPATH=scoreboard python -m pytest tests/ \
		--cov=scoreboard/app \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		-v

# ── Linting ──────────────────────────────────────────────────────────────────

lint: lint-py lint-go ## Run all linters

lint-py: ## Lint Python code with ruff
	ruff check scoreboard/app/ tests/

lint-go: ## Lint Go code
	cd scorebot && go vet ./...
	cd hill-agent && go vet ./...

# ── Formatting ───────────────────────────────────────────────────────────────

fmt: ## Format all code
	ruff format scoreboard/app/ tests/
	cd scorebot && gofmt -w .
	cd hill-agent && gofmt -w .

# ── Docker ───────────────────────────────────────────────────────────────────

build: ## Build Docker images
	docker compose build

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

logs: ## Tail logs from all services
	docker compose logs -f --tail=50

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml
	rm -rf scoreboard/app/__pycache__/
