.PHONY: install up down migrate api test test-all lint fmt

install:  ## Install Python deps and git hooks
	uv sync
	uv run pre-commit install

up:  ## Start Postgres and Redis
	docker compose up -d --wait

down:
	docker compose down

migrate:  ## Apply database migrations
	uv run alembic upgrade head

api:  ## Run the API with auto-reload
	uv run uvicorn shelfwise.api.main:app --reload

test:  ## Unit tests only (no services needed)
	uv run pytest -m "not integration and not llm"

test-all:  ## Everything, including integration tests (needs `make up`)
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

fmt:
	uv run ruff check --fix .
	uv run ruff format .
