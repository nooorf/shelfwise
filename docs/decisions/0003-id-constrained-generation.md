# 3. The LLM may only cite retrieved books: an ID enum in the output schema

**Status:** accepted, 2026-10-06; measured 2026-10-10 · **Design doc:** §18.2, §19

## Context

A library assistant that recommends a book the library doesn't have, or says a book is on the shelf when it's out, is worse than none. Local 4B–8B models invent plausible titles readily, and prompting "only use these books" reduces it without removing it.

## Decision

- Retrieval picks the books; the LLM only writes about them. Its output is JSON whose `work_id` field is an **enum of the candidate IDs**, enforced by constrained decoding (Ollama's `format`), so it cannot name another book's ID.
- Code renders title, author and availability **from the database**; the model never states availability.
- A validator checks every free-text piece before it reaches the reader: catalog titles and authors not among the shown books, availability words, numbers that must match the record, claim words absent from the record ("award", "bestseller"). A failing piece is replaced by its template on the spot, no retry, so streaming isn't held up.
- Lookups ("do you have *Dune*?") are answered from SQL with a template, never by the LLM.

## Consequences

Grounding set E (150 cases, Qwen3-8B on the 4090, `make eval-grounding`):

| System | Names books it wasn't given | Names books the library doesn't own | Treats made-up books as real | Talks about availability | Numbers or claims not in the record |
| --- | --- | --- | --- | --- | --- |
| LLM only (own memory) | n/a | 77% | 39% | 25% | 4% |
| Naive RAG (top 5, no checks) | 21% | | 25% | 23% | 47% |
| **Shelfwise** | **0%** | | **0%** | **0%** | **0%** |

The validator caught invented names in 29% of first drafts; 47% of answers used at least one template piece. The prose is plainer than a free-writing model's, which is the trade.
