"""Retrieval systems under evaluation, all with the same signature (design doc §29).

Each takes a query and returns ranked work ids. New systems register here, and the pooling and
evaluation scripts pick them up by name. Dense systems need an embedding model loaded into the
context (`SearchContext.build(..., embedder=...)`), rerank systems a reranker as well.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import Connection, text

from shelfwise.embed.encoder import Embedder
from shelfwise.query.constraints import Constraint
from shelfwise.query.rules import parse_rules
from shelfwise.ranking.rerank import CachedReranker, rerank
from shelfwise.retrieval.dense import DenseIndex
from shelfwise.retrieval.filters import allowed_mask
from shelfwise.retrieval.fusion import rrf
from shelfwise.retrieval.lexical import LexicalIndex, build_lexical_index
from shelfwise.retrieval.lookup import find_authors, find_by_isbn, find_titles

CANDIDATES = 100  # per channel, before fusion (design doc §13.2)
RERANK_DEPTH = 50  # default until the depth sweep picks one (design doc §14.2)


@dataclass
class SearchContext:
    conn: Connection
    index: LexicalIndex
    popularity: np.ndarray  # aligned with index.work_ids
    today: date
    embedder: Embedder | None = None
    dense: DenseIndex | None = None
    reranker: CachedReranker | None = None
    texts: dict[int, str] | None = None  # search_text per work, what the reranker reads
    rerank_depth: int = RERANK_DEPTH
    # Hard constraints added to every query's own, e.g. a facet filter under study.
    extra_constraints: tuple[Constraint, ...] = ()

    @classmethod
    def build(
        cls,
        conn: Connection,
        today: date | None = None,
        embedder: Embedder | None = None,
        reranker: CachedReranker | None = None,
    ) -> "SearchContext":
        index = build_lexical_index(conn)
        pop = {
            r.work_id: r.popularity
            for r in conn.execute(text("SELECT work_id, popularity FROM work"))
        }
        popularity = np.array([pop.get(int(w), 0.0) for w in index.work_ids], dtype=np.float64)
        dense_index = DenseIndex.load(conn, embedder.name, index.work_ids) if embedder else None
        texts: dict[int, str] | None = None
        if reranker is not None:
            rows = conn.execute(
                text("SELECT work_id, coalesce(search_text, title) AS body FROM work")
            )
            texts = {r.work_id: r.body for r in rows}
        return cls(
            conn, index, popularity, today or date.today(), embedder, dense_index, reranker, texts
        )

    def mask(self, query: str) -> tuple[np.ndarray, str]:
        parse = parse_rules(query, self.today)
        constraints = [*parse.constraints, *self.extra_constraints]
        return allowed_mask(self.conn, constraints, self.index.work_ids), parse.residual

    def require_reranker(self) -> tuple[CachedReranker, dict[int, str]]:
        if self.reranker is None or self.texts is None:
            raise RuntimeError("this system needs a reranker: pass --reranker")
        return self.reranker, self.texts

    def require_dense(self) -> tuple[Embedder, DenseIndex]:
        if self.embedder is None or self.dense is None:
            raise RuntimeError("this system needs an embedding model: pass --embedding-model")
        return self.embedder, self.dense


System = Callable[[SearchContext, str, int], list[int]]


def _allowed_ids(ctx: SearchContext, mask: np.ndarray) -> set[int]:
    return {int(w) for w, ok in zip(ctx.index.work_ids, mask, strict=True) if ok}


def _known_items(ctx: SearchContext, query: str) -> list[int]:
    """ISBN hits, then title and author matches merged by match score, an author's books by
    popularity. Merging by score means an author named in full ("agatha christie", 1.0) outranks
    titles that only resemble one query word (*Christy*); ties keep titles first."""
    popularity = dict(zip(ctx.index.work_ids.tolist(), ctx.popularity.tolist(), strict=True))
    matches = [(m.score, [m.work_id]) for m in find_titles(ctx.conn, query)]
    matches += [
        (a.score, sorted(a.work_ids, key=lambda w: -popularity.get(w, 0.0)))
        for a in find_authors(ctx.conn, query)
    ]
    matches.sort(key=lambda m: -m[0])  # stable
    return find_by_isbn(ctx.conn, query) + [w for _, ids in matches for w in ids]


def _semantic_text(query: str, residual: str) -> str:
    # The residual drops filter phrases ("under 300 pages"), which carry no meaning to embed.
    return residual or query


def bm25_raw(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Keyword search on the raw query, no parsing, no filters (the OPAC-style floor)."""
    return [h.work_id for h in ctx.index.search(query, k)]


def bm25(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Rule parser -> hard filters -> BM25 on the residual text."""
    mask, residual = ctx.mask(query)
    return [h.work_id for h in ctx.index.search(residual, k, allowed=mask)]


def bm25_lookup(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Known-item lookups first, then BM25."""
    mask, residual = ctx.mask(query)
    lexical = [h.work_id for h in ctx.index.search(residual, k * 2, allowed=mask)]
    allowed = _allowed_ids(ctx, mask)
    return [w for w in dict.fromkeys(_known_items(ctx, query) + lexical) if w in allowed][:k]


def dense(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Rule parser -> hard filters -> embedding similarity on the residual text."""
    embedder, index = ctx.require_dense()
    mask, residual = ctx.mask(query)
    vector = embedder.encode_query(_semantic_text(query, residual))
    return [h.work_id for h in index.search(vector, k, allowed=mask)]


def _hybrid_ranking(ctx: SearchContext, query: str, mask: np.ndarray, residual: str) -> list[int]:
    embedder, index = ctx.require_dense()
    lexical = [h.work_id for h in ctx.index.search(residual, CANDIDATES, allowed=mask)]
    vector = embedder.encode_query(_semantic_text(query, residual))
    semantic = [h.work_id for h in index.search(vector, CANDIDATES, allowed=mask)]
    return [doc for doc, _ in rrf([lexical, semantic])]


def hybrid(ctx: SearchContext, query: str, k: int) -> list[int]:
    """BM25 and dense lists, both filtered, merged with untuned RRF (k=60, equal weights)."""
    mask, residual = ctx.mask(query)
    return _hybrid_ranking(ctx, query, mask, residual)[:k]


def hybrid_lookup(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Known-item lookups first, then hybrid."""
    mask, residual = ctx.mask(query)
    ranked = _known_items(ctx, query) + _hybrid_ranking(ctx, query, mask, residual)
    allowed = _allowed_ids(ctx, mask)
    return [w for w in dict.fromkeys(ranked) if w in allowed][:k]


def hybrid_rerank(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Known-item lookups first, then the top `rerank_depth` hybrid results reordered by the
    cross-encoder. Lookups stay on top: a reranker shouldn't bury the exact book asked for."""
    reranker, texts = ctx.require_reranker()
    mask, residual = ctx.mask(query)
    hybrid_ranked = _hybrid_ranking(ctx, query, mask, residual)
    reranked = rerank(
        reranker, _semantic_text(query, residual), hybrid_ranked, texts, ctx.rerank_depth
    )
    allowed = _allowed_ids(ctx, mask)
    ranked = _known_items(ctx, query) + [w for w, _ in reranked]
    return [w for w in dict.fromkeys(ranked) if w in allowed][:k]


def popular(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Most-borrowed works that pass the hard filters; ignores the query's meaning."""
    mask, _ = ctx.mask(query)
    order = np.argsort(-np.where(mask, ctx.popularity, -1.0), kind="stable")
    return [int(ctx.index.work_ids[i]) for i in order[:k] if mask[i]]


def random_filtered(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Uniform sample of works that pass the hard filters (seeded by the query)."""
    mask, _ = ctx.mask(query)
    candidates = sorted(_allowed_ids(ctx, mask))
    return random.Random(query).sample(candidates, min(k, len(candidates)))


SYSTEMS: dict[str, System] = {
    "random": random_filtered,
    "popular": popular,
    "bm25_raw": bm25_raw,
    "bm25": bm25,
    "bm25_lookup": bm25_lookup,
    "dense": dense,
    "hybrid": hybrid,
    "hybrid_lookup": hybrid_lookup,
    "hybrid_rerank": hybrid_rerank,
}
DENSE_SYSTEMS = ("dense", "hybrid", "hybrid_lookup", "hybrid_rerank")
RERANK_SYSTEMS = ("hybrid_rerank",)
# Systems whose results go into the judging pool. Random adds labeling cost for little value.
POOL_SYSTEMS = ("popular", "bm25_raw", "bm25", "bm25_lookup", *DENSE_SYSTEMS)  # incl. rerank


def available_systems(ctx: SearchContext, names: list[str]) -> list[str]:
    """Drop dense systems when no embedding model is loaded, rerank ones without a reranker."""
    return [
        n
        for n in names
        if (ctx.dense is not None or n not in DENSE_SYSTEMS)
        and (ctx.reranker is not None or n not in RERANK_SYSTEMS)
    ]


def load_context(
    conn: Connection,
    embedding_model: str | None,
    today: date | None = None,
    reranker_model: str | None = None,
) -> SearchContext:
    """Search context with the dense index when embeddings exist for the model; otherwise
    lexical-only, with a note (so scripts still run before `make embed`). A reranker is loaded
    only when named: it is the slowest model in the pipeline."""
    reranker = None
    if reranker_model:
        from shelfwise.ranking.rerank import load_reranker

        reranker = load_reranker(reranker_model)
    if embedding_model:
        stored = conn.execute(
            text("SELECT count(*) FROM work_embedding WHERE model_name = :m"),
            {"m": embedding_model},
        ).scalar_one()
        if stored:
            from shelfwise.embed.encoder import load_embedder

            return SearchContext.build(
                conn, today, embedder=load_embedder(embedding_model), reranker=reranker
            )
        print(
            f"note: no {embedding_model!r} embeddings yet (run `make embed`); dense systems skipped"
        )
    return SearchContext.build(conn, today, reranker=reranker)
