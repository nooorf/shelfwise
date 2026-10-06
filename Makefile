.PHONY: install up down migrate seed-sample import-seed simulate tick embed llm llm-pull pool label eval api test test-all lint fmt

install:  ## Install Python deps and git hooks
	uv sync
	uv run pre-commit install

up:  ## Start Postgres and Redis
	docker compose up -d --wait

down:
	docker compose down

migrate:  ## Apply database migrations
	uv run alembic upgrade head

seed-sample:  ## Regenerate data/seed/isbns.csv from Open Library searches
	uv run python scripts/sample_seed_isbns.py

import-seed:  ## Import data/seed/isbns.csv (cached lookups; safe to re-run)
	uv run python scripts/import_isbns.py data/seed/isbns.csv --source seed

simulate:  ## Shelve every book and simulate 12 months of circulation (replaces copies/loans)
	uv run python scripts/simulate_library.py

tick:  ## Keep availability changing during a demo (Ctrl-C to stop)
	uv run python scripts/availability_tick.py --interval 60

llm:  ## Run the local LLM server (leave it running in its own terminal)
	ollama serve

llm-pull:  ## Download the configured LLM (SHELFWISE_LLM_MODEL, default qwen3:4b)
	ollama pull $${SHELFWISE_LLM_MODEL:-qwen3:4b}

embed:  ## Embed new or changed books with the default model (MODEL=all for every model)
	uv run python scripts/embed.py $(if $(MODEL),--model $(MODEL),)

pool:  ## Add every search system's top 10 per query to eval/data/qrels.csv
	uv run python scripts/pool.py

label:  ## Grade pooled books: make label JUDGE=<your initials>
	@test -n "$(JUDGE)" || (echo "usage: make label JUDGE=<your initials>" && exit 1)
	uv run python scripts/label.py --judge $(JUDGE)

eval:  ## Score all systems on the dev split and save a report
	uv run python scripts/evaluate.py

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
