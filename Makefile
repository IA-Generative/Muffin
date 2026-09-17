# =============================================================================
# Muffin — developer entrypoint
#
# `make` (or `make help`) lists every target grouped by topic.
# =============================================================================

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

# Colors for terminal output
COLOR_RESET   := \033[0m
COLOR_BOLD    := \033[1m
COLOR_DIM     := \033[2m
COLOR_RED     := \033[31m
COLOR_GREEN   := \033[32m
COLOR_YELLOW  := \033[33m
COLOR_BLUE    := \033[34m
COLOR_CYAN    := \033[36m

# Runtime
UV      := uv
PNPM    := pnpm
DOCKER_COMPOSE := docker compose
FRONTEND_DIR := frontend
BACKEND_DIR   := backend

.DEFAULT_GOAL := help

# Guard: fail with an actionable message instead of a cryptic "command not found".
define _require
	@command -v $(1) >/dev/null 2>&1 || { \
		echo "$(COLOR_RED)✗$(COLOR_RESET) $(1) is required but not installed. $(2)"; \
		exit 1; \
	}
endef

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo "$(COLOR_BOLD)$(COLOR_CYAN)  Muffin — available commands$(COLOR_RESET)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} \
		/^## / { printf "\n$(COLOR_BOLD)$(COLOR_YELLOW)%s$(COLOR_RESET)\n", substr($$0, 4) } \
		/^[a-zA-Z0-9_.-]+:.*##/ { printf "  $(COLOR_CYAN)%-32s$(COLOR_RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""

# -----------------------------------------------------------------------------
## ▸ Setup
# -----------------------------------------------------------------------------

.PHONY: install
install: install-uv install-hooks install-backend ## Install everything (uv, git hooks, backend deps)
	@echo "$(COLOR_BOLD)$(COLOR_GREEN)  ✓ Workspace ready$(COLOR_RESET)"
	@echo "$(COLOR_DIM)  Run 'make check' to validate the repo$(COLOR_RESET)"

.PHONY: install-backend
install-backend: install-uv ## Sync the backend virtualenv (backend/.venv)
	@echo "$(COLOR_BLUE)→$(COLOR_RESET) Syncing backend dependencies..."
	@cd $(BACKEND_DIR) && $(UV) sync --group dev
	@echo "$(COLOR_GREEN)✓$(COLOR_RESET) Backend dependencies synced"

.PHONY: install-uv
install-uv: ## Install the uv Python package manager if missing
	@if ! command -v $(UV) >/dev/null 2>&1; then \
		echo "$(COLOR_BLUE)→$(COLOR_RESET) uv not found, installing..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	else \
		echo "$(COLOR_GREEN)✓$(COLOR_RESET) uv already installed"; \
	fi

.PHONY: install-hooks
install-hooks: ## Install pre-commit and its git hooks (incl. gitleaks)
	@if ! command -v pre-commit >/dev/null 2>&1; then \
		echo "$(COLOR_BLUE)→$(COLOR_RESET) pre-commit not found, installing..."; \
		$(UV) tool install pre-commit; \
	else \
		echo "$(COLOR_GREEN)✓$(COLOR_RESET) pre-commit already installed"; \
	fi
	@echo "$(COLOR_BLUE)→$(COLOR_RESET) Installing git hooks..."
	@pre-commit install
	@pre-commit install --hook-type commit-msg
	@echo "$(COLOR_GREEN)✓$(COLOR_RESET) Git hooks installed"

.PHONY: doctor
doctor: ## Report which required tools are present on this machine
	@echo ""
	@echo "$(COLOR_BOLD)  Toolchain$(COLOR_RESET)"
	@for tool in uv pre-commit git; do \
		if command -v $$tool >/dev/null 2>&1; then \
			printf "  $(COLOR_GREEN)✓$(COLOR_RESET) %-12s %s\n" "$$tool" "$$($$tool --version 2>&1 | head -1)"; \
		else \
			printf "  $(COLOR_RED)✗$(COLOR_RESET) %-12s missing\n" "$$tool"; \
		fi; \
	done
	@echo ""

# -----------------------------------------------------------------------------
## ▸ Development
# -----------------------------------------------------------------------------

.PHONY: front
front: ## Start the frontend dev server with hot reload (http://localhost:5173)
	$(call _require,$(PNPM),See https://pnpm.io/installation)
	@if [ ! -d $(FRONTEND_DIR)/node_modules ]; then \
		echo "$(COLOR_BLUE)→$(COLOR_RESET) Installing frontend dependencies..."; \
		$(PNPM) --dir $(FRONTEND_DIR) install; \
	fi
	@$(PNPM) --dir $(FRONTEND_DIR) dev

.PHONY: back
back: ## Start the backend dev server with hot reload (http://localhost:8000/api/docs)
	@cd $(BACKEND_DIR) && $(UV) run uvicorn app.main:app --reload --port 8000

.PHONY: up
up: ## Start the full stack (frontend, backend, Postgres, Redis, Keycloak) in Docker
	@$(DOCKER_COMPOSE) up -d

.PHONY: down
down: ## Stop the full Docker stack
	@$(DOCKER_COMPOSE) down

.PHONY: migrate
migrate: ## Apply pending Alembic migrations to the local Postgres
	@cd $(BACKEND_DIR) && $(UV) run alembic upgrade head

.PHONY: migration
migration: ## Generate a new Alembic migration from model changes (usage: make migration m="message")
	@cd $(BACKEND_DIR) && $(UV) run alembic revision --autogenerate -m "$(m)"

# -----------------------------------------------------------------------------
## ▸ Checks
# -----------------------------------------------------------------------------

.PHONY: check
check: ## Run all pre-commit hooks against every file (ruff, gitleaks, ...)
	$(call _require,pre-commit,Run 'make install-hooks' first)
	@pre-commit run --all-files

.PHONY: gitleaks
gitleaks: ## Run gitleaks alone against the full git history
	$(call _require,pre-commit,Run 'make install-hooks' first)
	@pre-commit run gitleaks --all-files --hook-stage manual

.PHONY: lint-backend
lint-backend: ## Lint and format-check the backend (ruff)
	@cd $(BACKEND_DIR) && $(UV) run ruff check . && $(UV) run ruff format --check .

TEST_DATABASE_URL := postgresql+asyncpg://muffin:muffin@localhost:55432/muffin
TEST_REDIS_URL     := redis://localhost:56379/0

.PHONY: test-backend
test-backend: ## Run backend unit tests against a throwaway Postgres/Redis
	@$(DOCKER_COMPOSE) -f docker-compose-test.yaml up -d --wait
	@cd $(BACKEND_DIR) && \
		(DATABASE_URL=$(TEST_DATABASE_URL) $(UV) run alembic upgrade head && \
		DATABASE_URL=$(TEST_DATABASE_URL) REDIS_URL=$(TEST_REDIS_URL) $(UV) run pytest; status=$$?; \
		cd .. && $(DOCKER_COMPOSE) -f docker-compose-test.yaml down -v; \
		exit $$status)
