# Optimism FastAPI — developer workflow (plan §1, §2).
.PHONY: dev install lint format typecheck test test-unit test-api test-integration coverage verify migrate up down logs secret hash clean

VENV := .venv/bin
UV := uv
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.tools/uv-python

install: ## Create venv and install locked dependencies
	$(UV) sync

dev: ## Run the API + web app with uvicorn (auto-reload)
	$(VENV)/uvicorn app.main:app --reload --port 8000

up: ## Start the docker compose stack (migrations run on startup)
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f web

lint: ## Ruff lint
	$(VENV)/ruff check app tests

format: ## Ruff format
	$(VENV)/ruff format app tests

typecheck: ## mypy strict (app) + pragmatic (tests)
	$(VENV)/mypy app tests

test: ## Full pytest suite (PostgreSQL integration tests skip without PG)
	$(VENV)/pytest -p no:warnings

test-unit:
	$(VENV)/pytest tests/unit tests/api tests/web -p no:warnings

test-integration: ## Requires PostgreSQL (TEST_DATABASE_URL, default localhost:5432/optimism_test)
	$(VENV)/pytest tests/integration -p no:warnings

coverage: ## Branch coverage report (80% floor per plan §1)
	$(VENV)/pytest --cov=app --cov-branch --cov-report=term-missing --cov-report=xml -p no:warnings

verify: lint format-check typecheck test ## Full local verification

format-check:
	$(VENV)/ruff format --check app tests

migrate: ## Apply Alembic migrations to the configured DATABASE_URL
	$(VENV)/alembic upgrade head

hash: ## Generate a bcrypt cost-12 hash for the shared admin password
	$(VENV)/python -c "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass('password: ').encode(), bcrypt.gensalt(rounds=12)).decode())"

secret: ## Write the docker compose secret files (dev defaults)
	mkdir -p secrets
	@test -f secrets/db_password.txt || echo "optimism" > secrets/db_password.txt
	@test -f secrets/session_secret.txt || $(VENV)/python -c "import secrets; open('secrets/session_secret.txt','w').write(secrets.token_urlsafe(48))"
	@test -f secrets/admin_hash.txt || $(VENV)/python -c "import bcrypt; open('secrets/admin_hash.txt','w').write(bcrypt.hashpw(b'change-me', bcrypt.gensalt(rounds=12)).decode())"
	@echo "Secret files ready (admin password: change-me)"

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
