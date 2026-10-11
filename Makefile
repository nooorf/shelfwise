.PHONY: install up down migrate seed-sample import-seed drop-non-english download-goodreads build-catalog review-duplicates simulate featured tick embed llm llm-pull tag label-tags tags-doc import-tags label-violations violation-agreement negation-study synth-requests training-set train-embedder train-reranker score-tags pool label grades-doc import-grades blind-doc import-blind label-blind agreement eval eval-grounding eval-parser eval-conversations download-tts download-stt download-avatar api web web-install web-test web-e2e measure web-build web-types test test-all lint fmt

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

featured:  ## Choose the landing page's featured shelf and look up the covers (data/seed/featured.csv)
	uv run python scripts/pick_featured.py

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

tags-doc:  ## Write eval/tags_review.md: the labelling sample with Claude's suggested tags
	uv run python scripts/tags_doc.py export

import-tags:  ## Save your reviewed eval/tags_review.md: make import-tags JUDGE=<initials>
	@test -n "$(JUDGE)" || (echo "usage: make import-tags JUDGE=<your initials>" && exit 1)
	uv run python scripts/tags_doc.py import --judge $(JUDGE)

label-violations:  ## Negation study tags: make label-violations JUDGE=<initials> (SAMPLE=claude: blind check of ~60 of Claude's)
	@test -n "$(JUDGE)" || (echo "usage: make label-violations JUDGE=<your initials>" && exit 1)
	uv run python scripts/label_violations.py --judge $(JUDGE) $(if $(SAMPLE),--sample-of $(SAMPLE),)

violation-agreement:  ## Blind check of the negation-study tags: make violation-agreement JUDGE=<initials> (after SAMPLE=claude labelling)
	@test -n "$(JUDGE)" || (echo "usage: make violation-agreement JUDGE=<your initials>" && exit 1)
	uv run python scripts/violation_agreement.py --judges claude $(JUDGE)

negation-study:  ## Run the negation study: make negation-study JUDGE=<initials> (RERANKER=minilm adds rerank)
	@test -n "$(JUDGE)" || (echo "usage: make negation-study JUDGE=<your initials>" && exit 1)
	uv run python scripts/negation_study.py --judge $(JUDGE) $(if $(RERANKER),--reranker $(RERANKER),)

synth-requests:  ## Two synthetic reader requests per book, training data (needs make llm; MODEL=qwen3:8b; resumable)
	uv run python scripts/make_synthetic_requests.py $(if $(MODEL),--model $(MODEL),)

training-set:  ## Fine-tuning data from graded dev queries + synthetic requests (SUBSET=0.05 for a small one)
	uv run --group train python scripts/build_training_set.py $(if $(SUBSET),--subset $(SUBSET),)

train-embedder:  ## Fine-tune the embedder into models/bge-base-ft (ARGS="--max-steps 30" smoke test), then make embed MODEL=bge-base-ft
	uv run --group train python scripts/train_embedder.py $(ARGS)

train-reranker:  ## Fine-tune a reranker into models/<base>-rerank-ft (ARGS="--base minilm --max-steps 30" smoke test)
	uv run --group train python scripts/train_reranker.py $(ARGS)

score-tags:  ## Score the LLM's book tags against the hand labels
	uv run python scripts/score_tags.py

embed:  ## Embed new or changed books with the default model (MODEL=all for every model)
	uv run python scripts/embed.py $(if $(MODEL),--model $(MODEL),)

pool:  ## Add every search system's top 10 per query to eval/data/qrels.csv (RERANKER=minilm adds hybrid_rerank, PARSER=cascade adds parsed_hybrid)
	uv run python scripts/pool.py $(if $(RERANKER),--reranker $(RERANKER),) $(if $(PARSER),--parser $(PARSER),)

label:  ## Grade pooled books: make label JUDGE=<your initials>
	@test -n "$(JUDGE)" || (echo "usage: make label JUDGE=<your initials>" && exit 1)
	uv run python scripts/label.py --judge $(JUDGE)

grades-doc:  ## Write eval/grades_review.md: every query, its books and the suggested grades
	uv run python scripts/grades_doc.py export

import-grades:  ## Save your reviewed eval/grades_review.md: make import-grades JUDGE=<initials>
	@test -n "$(JUDGE)" || (echo "usage: make import-grades JUDGE=<your initials>" && exit 1)
	uv run python scripts/grades_doc.py import --judge $(JUDGE)

blind-doc:  ## Write eval/blind_review.md: the blind agreement sample, grade cells empty
	uv run python scripts/blind.py doc

import-blind:  ## Save your grades from eval/blind_review.md: make import-blind JUDGE=<initials>
	@test -n "$(JUDGE)" || (echo "usage: make import-blind JUDGE=<your initials>" && exit 1)
	uv run python scripts/blind.py import --judge $(JUDGE)

label-blind:  ## Grade the blind agreement sample (Claude's grades hidden): make label-blind JUDGE=<initials>
	@test -n "$(JUDGE)" || (echo "usage: make label-blind JUDGE=<your initials>" && exit 1)
	uv run python scripts/label.py --judge $(JUDGE) --qrels eval/data/blind_sample.csv

agreement:  ## Agreement between your blind grades and Claude's: make agreement JUDGE=<initials>
	@test -n "$(JUDGE)" || (echo "usage: make agreement JUDGE=<your initials>" && exit 1)
	uv run python scripts/blind.py score --judge $(JUDGE)

eval:  ## Score all systems on the dev split and save a report (RERANKER=minilm adds hybrid_rerank, PARSER=cascade adds parsed_hybrid)
	uv run python scripts/evaluate.py $(if $(RERANKER),--reranker $(RERANKER),) $(if $(PARSER),--parser $(PARSER),)

eval-grounding:  ## Grounding set E: invented books, availability talk, claims; full system vs naive RAG vs LLM-only (needs make llm; resumable; PER_KIND=2 for a quick look, MODEL=qwen3:8b, REDO=full)
	uv run python scripts/eval_grounding.py $(if $(PER_KIND),--per-kind $(PER_KIND),) $(if $(MODEL),--model $(MODEL),) $(if $(REDO),--redo $(REDO),)

eval-parser:  ## Score the query parser against gold set B (PARSER=rules|cascade, SPLIT=dev|test|all, ERRORS=1)
	uv run python scripts/eval_parser.py --parser $(or $(PARSER),rules) --split $(or $(SPLIT),dev) \
		$(if $(MODEL),--model $(MODEL),) $(if $(ERRORS),--errors,)

eval-conversations:  ## Play conversation set C and score the state after every turn (PARSER=rules|cascade, ERRORS=1)
	uv run python scripts/eval_conversations.py --parser $(or $(PARSER),rules) $(if $(ERRORS),--errors,)

TTS_URL = https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
download-tts:  ## Download the Kokoro text-to-speech model (~120 MB) into data/models/kokoro
	mkdir -p data/models/kokoro
	cd data/models/kokoro && for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do \
		[ -f $$f ] || curl -fL --progress-bar -o $$f $(TTS_URL)/$$f; done

VAD_URL = https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.3/src/silero_vad/data/silero_vad.onnx
download-stt:  ## Download Silero VAD (~2 MB) for voice input; Whisper (~0.5 GB) downloads on first use
	mkdir -p data/models/silero
	[ -f data/models/silero/silero_vad.onnx ] || curl -fL --progress-bar -o data/models/silero/silero_vad.onnx $(VAD_URL)

AVATAR_URL = https://raw.githubusercontent.com/vrm-c/vrm-specification/master/samples/VRM1_Constraint_Twist_Sample/vrm/VRM1_Constraint_Twist_Sample.vrm
download-avatar:  ## Download the placeholder avatar (pixiv's VRM 1.0 sample, ~11 MB) until your VRoid model exists
	mkdir -p apps/web/public/avatar
	[ -f apps/web/public/avatar/sample.vrm ] || curl -fL --progress-bar -o apps/web/public/avatar/sample.vrm $(AVATAR_URL)

api:  ## Run the API with auto-reload
	uv run uvicorn shelfwise.api.main:app --reload

# The web app (apps/web). Node is the official prebuilt LTS in ~/.local/node (Homebrew has no
# bottle for this macOS and builds it from source); NODE_BIN= points elsewhere if you have one.
NODE_BIN ?= $(HOME)/.local/node/bin
WEB = cd apps/web && PATH="$(NODE_BIN):$$PATH"

web:  ## Run the web app at http://localhost:5173 (needs `make api` in another terminal)
	$(WEB) npm run dev

web-install:  ## Install the web app's packages exactly as locked
	$(WEB) npm ci

web-test:  ## Run the web app's tests
	$(WEB) npx vitest run

web-e2e:  ## Browser tests against the real API and database (needs `make up`; starts the API and web app unless they're running)
	$(WEB) npx playwright test

measure:  ## Voice measurements: time to first audio (avatar on vs off), lip-sync offset, FPS, avatar load; a browser window opens (~20 min; needs `make up`, `make llm` for the real parse; UTTERANCES=5 for a quick look)
	$(WEB) npx playwright test -c playwright.measure.config.ts

web-build:  ## Type-check and build the web app into apps/web/dist
	$(WEB) npm run build

web-types:  ## Regenerate the web app's API types after the API changes
	uv run python scripts/export_openapi.py apps/web/src/api/openapi.json
	$(WEB) npx --yes openapi-typescript@7 src/api/openapi.json -o src/api/schema.d.ts

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
