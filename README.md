# Shelfwise

Conversational library search that turns requests like *"dark, psychological, nothing supernatural, under 300 pages, on the shelf today"* into book recommendations that exist in the inventory and satisfy every hard constraint. Hybrid retrieval, cross-encoder reranking and a local LLM that may only cite retrieved books. Fully local, no paid APIs.

**Status:** early development. No results yet; benchmark numbers will appear here once measured.

- Design: [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)
- Plan and progress: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env
make install     # Python 3.12 env + git hooks
make up          # Postgres (pgvector) + Redis
make migrate     # create the catalog schema
make test        # unit tests (make test-all adds integration tests)
make api         # http://localhost:8000/api/v1/health
```
