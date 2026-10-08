# Shelfwise

Conversational library search that turns requests like *"dark, psychological, nothing supernatural, under 300 pages, on the shelf today"* into book recommendations that exist in the inventory and satisfy every hard constraint. Hybrid retrieval, cross-encoder reranking and a local LLM that may only cite retrieved books. Fully local, no paid APIs.

**Status:** early development. Book metadata is real (Open Library, and Goodreads via the UCSD Book Graph); copies and circulation are simulated. No results yet; benchmark numbers will appear here once measured.

- Design: [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)
- How relevance is graded: [eval/GRADING.md](eval/GRADING.md)

## Quickstart

Requires [uv](https://docs.astral.sh/uv/), Docker and [Ollama](https://ollama.com).

```bash
cp .env.example .env
make install     # Python 3.12 env + git hooks
make up          # Postgres (pgvector) + Redis
make migrate     # create the catalog schema
make import-seed # load the seed shelf from Open Library (~5 min first time, cached after)
make download-goodreads  # UCSD Book Graph subsets, ~1.6 GB (academic use only)
make build-catalog       # import ~5,000 works from them (~10 min)
make simulate    # shelves, copies and 12 months of simulated circulation
make test        # unit tests (make test-all adds integration tests)
make embed       # embed the books for meaning-based search
make llm         # in a second terminal: the local LLM server
make llm-pull    # download the LLM (~2.5 GB)
make api         # http://localhost:8000/api/v1/health
```

## Data

- **Open Library** ([openlibrary.org](https://openlibrary.org)): edition and work metadata for the seed shelf.
- **UCSD Book Graph** ([Goodreads datasets](https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/UCSD%20Book%20Graph.html)), collected in 2017 for academic use only. The raw files are downloaded by `make download-goodreads` and never committed or redistributed. Cite: Mengting Wan and Julian McAuley, "Item Recommendation on Monotonic Behavior Chains", RecSys 2018; Mengting Wan, Rishabh Misra, Ndapa Nakashole and Julian McAuley, "Fine-Grained Spoiler Detection from Large-Scale Review Corpora", ACL 2019.
