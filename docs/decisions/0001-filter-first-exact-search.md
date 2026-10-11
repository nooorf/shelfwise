# 1. Filter first, then exact vector search in memory

**Status:** accepted, 2026-10-06 · **Design doc:** §13, §32

## Context

A request mixes hard facts and taste: *"a dark thriller under 300 pages, on the shelf today"*. The hard part (pages, availability, language, an excluded tag) must hold for every book shown; the taste part ranks what is left. Vector databases usually do this the other way round: approximate nearest-neighbour search first, then filter. With a selective filter that loses recall, sometimes all of it: the 100 nearest books may contain none that are available and short.

The catalog is about 5,400 works, and a library's is unlikely to pass a few hundred thousand.

## Decision

1. Hard constraints become one SQL query that returns the **allowed IDs**.
2. BM25 and the embedding matrix live **in memory** (NumPy), loaded from Postgres at startup and whenever the catalog version changes.
3. Every channel scores only the allowed IDs, exactly: a matrix-vector product over the mask, no ANN index.
4. pgvector stays the store of record, and the way to scale past ~500k works (HNSW with iterative scans).

## Consequences

- No book outside the hard constraints can be shown, by construction. That's the property the UI's "must" chips promise.
- Exact search has perfect recall, so there is no index to tune and nothing to explain in an evaluation.
- Search is fast: dense retrieval p95 32 ms and hybrid 7 ms on the 8 GB M2 (`make eval`, dev split). The shipped `parsed_hybrid` spends ~250 ms p95, almost all of it outside the vector math.
- Memory grows linearly with the catalog: 5,400 × 768 floats is ~16 MB, so far from a problem at this scale.
- Rejected: FAISS, Qdrant or Chroma (a second datastore to keep in sync, no gain at this size); pgvector HNSW with post-filtering (the recall loss above).
