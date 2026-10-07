.PHONY: install up down migrate seed-sample import-seed drop-non-english download-goodreads build-catalog review-duplicates simulate tick embed llm llm-pull tag label-tags score-tags pool label grades-doc import-grades eval api test test-all lint fmt

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

GOODREADS_URL := https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads
GOODREADS_SUBSETS := mystery_thriller_crime fantasy_paranormal history_biography romance young_adult children comics_graphic poetry

drop-non-english:  ## List non-English books; APPLY=1 removes them (stop `make tag` first)
	uv run python scripts/drop_non_english.py $(if $(APPLY),--apply,)

download-goodreads:  ## Download the UCSD Book Graph subsets (~1.6 GB, academic use only; resumable)
	mkdir -p data/raw/goodreads
	for f in goodreads_book_authors goodreads_book_works; do \
		curl -fL -C - --retry 3 -o data/raw/goodreads/$$f.json.gz $(GOODREADS_URL)/$$f.json.gz || exit 1; done
	for s in $(GOODREADS_SUBSETS); do \
		curl -fL -C - --retry 3 -o data/raw/goodreads/goodreads_books_$$s.json.gz \
			$(GOODREADS_URL)/byGenre/goodreads_books_$$s.json.gz || exit 1; done

build-catalog:  ## Import ~5,000 works from the Goodreads subsets (TOTAL=8000 for more)
	uv run python scripts/build_catalog.py $(if $(TOTAL),--total $(TOTAL),)

review-duplicates:  ## Decide which near-duplicate works are one book (approved ones are merged)
	uv run python scripts/review_duplicates.py

simulate:  ## Shelve every book and simulate 12 months of circulation (replaces copies/loans)
	uv run python scripts/simulate_library.py

tick:  ## Keep availability changing during a demo (Ctrl-C to stop)
	uv run python scripts/availability_tick.py --interval 60

llm:  ## Run the local LLM server (leave it running in its own terminal)
	ollama serve

llm-pull:  ## Download the configured LLM (SHELFWISE_LLM_MODEL, default qwen3:4b)
	ollama pull $${SHELFWISE_LLM_MODEL:-qwen3:4b}

tag:  ## Tag untagged books with the local LLM (resumable; needs `make llm`), then re-embed
	uv run python scripts/tag_books.py
	uv run python scripts/embed.py

label-tags:  ## Hand-label book tags: make label-tags JUDGE=<your initials>
	@test -n "$(JUDGE)" || (echo "usage: make label-tags JUDGE=<your initials>" && exit 1)
	uv run python scripts/label_tags.py --judge $(JUDGE)

score-tags:  ## Score the LLM's book tags against the hand labels
	uv run python scripts/score_tags.py

embed:  ## Embed new or changed books with the default model (MODEL=all for every model)
	uv run python scripts/embed.py $(if $(MODEL),--model $(MODEL),)

pool:  ## Add every search system's top 10 per query to eval/data/qrels.csv (RERANKER=minilm adds hybrid_rerank)
	uv run python scripts/pool.py $(if $(RERANKER),--reranker $(RERANKER),)

label:  ## Grade pooled books: make label JUDGE=<your initials>
	@test -n "$(JUDGE)" || (echo "usage: make label JUDGE=<your initials>" && exit 1)
	uv run python scripts/label.py --judge $(JUDGE)

grades-doc:  ## Write eval/grades_review.md: every query, its books and the suggested grades
	uv run python scripts/grades_doc.py export

import-grades:  ## Save your reviewed eval/grades_review.md: make import-grades JUDGE=<initials>
	@test -n "$(JUDGE)" || (echo "usage: make import-grades JUDGE=<your initials>" && exit 1)
	uv run python scripts/grades_doc.py import --judge $(JUDGE)

eval:  ## Score all systems on the dev split and save a report (RERANKER=minilm adds hybrid_rerank)
	uv run python scripts/evaluate.py $(if $(RERANKER),--reranker $(RERANKER),)

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
