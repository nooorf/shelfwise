"""Retrieval systems under evaluation, all with the same signature (design doc §29).

Each takes a query and returns ranked work ids. New systems register here, and the pooling and
evaluation scripts pick them up by name. Dense systems need an embedding model loaded into the
context (`SearchContext.build(..., embedder=...)`), rerank systems a reranker as well, and
parsed systems a query parser (`load_context(..., parser="cascade")`).
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import Connection, text

from shelfwise.embed.encoder import Embedder
from shelfwise.query.constraints import Constraint
from shelfwise.query.request import ParsedRequest
from shelfwise.query.rules import parse_rules
from shelfwise.ranking.rerank import CachedReranker, rerank
from shelfwise.ranking.soft import SOFT_WEIGHT, soft_score
from shelfwise.retrieval.dense import DenseIndex
from shelfwise.retrieval.filters import FACET_COLUMNS, allowed_mask
from shelfwise.retrieval.fusion import rrf
from shelfwise.retrieval.lexical import LexicalIndex, build_lexical_index
from shelfwise.retrieval.lookup import find_authors, find_by_isbn, find_titles

CANDIDATES = 100  # per channel, before fusion (design doc §13.2)
# Relevance floor for parsed_hybrid's embedding searches: a book more than this below the best
# match in the catalog is dropped. On the dev split's graded pairs (bge-base, 2026-10-08) 0.20
# keeps 99.9% of relevant books (grade 2-3) and drops 30% of grade-0 ones.
MAX_GAP = 0.20
RERANK_DEPTH = 50  # default until the depth sweep picks one (design doc §14.2)
# The LLM's answers for every evaluated query, so benchmark runs don't need Ollama (committed).
LLM_CACHE = Path("eval/data/llm_cache.jsonl")
PARSERS = ("cascade",)

Parser = Callable[[str, date], ParsedRequest]
_BOOK_NUMBERS = text(
    """
    SELECT w.work_id, w.genres,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages,
           coalesce(w.first_pub_year,
                    (SELECT min(e.pub_year) FROM edition e WHERE e.work_id = w.work_id)) AS year
    FROM work w
    """
)


@dataclass(frozen=True)
class BookSignals:
    """Per-book data the soft-constraint score reads, loaded once per context."""

    facets: dict[int, dict[str, Any]]
    genres: dict[int, list[str]]
    popularity_rank: dict[int, float]  # percentile, 1.0 = most borrowed
    pages: dict[int, int]  # longest edition, as the cards show
    year: dict[int, int]  # first publication, else the earliest edition


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
    parser: Parser | None = None  # for the parsed systems; the others use the rules directly
    parse_fallbacks: list[str] = field(default_factory=list)  # queries the LLM couldn't parse
    _parses: dict[str, ParsedRequest] = field(default_factory=dict)
    _signals: BookSignals | None = None

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

    def parsed(self, query: str) -> ParsedRequest:
        """The parser's reading of `query`, parsed once per context (systems share it)."""
        if self.parser is None:
            raise RuntimeError("this system needs a query parser: pass --parser cascade")
        if query not in self._parses:
            self._parses[query] = self.parser(query, self.today)
        return self._parses[query]

    def signals(self) -> BookSignals:
        if self._signals is None:
            columns = ", ".join(FACET_COLUMNS)
            facets = {
                r.work_id: dict(r._mapping)
                for r in self.conn.execute(text(f"SELECT work_id, {columns} FROM work_facets"))
            }
            genres, pages, year = {}, {}, {}
            for r in self.conn.execute(_BOOK_NUMBERS):
                genres[r.work_id] = list(r.genres or [])
                if r.pages:
                    pages[r.work_id] = r.pages
                if r.year:
                    year[r.work_id] = r.year
            order = np.argsort(np.argsort(self.popularity, kind="stable"), kind="stable")
            ranks = order / max(len(order) - 1, 1)
            popularity_rank = dict(zip(self.index.work_ids.tolist(), ranks.tolist(), strict=True))
            self._signals = BookSignals(facets, genres, popularity_rank, pages, year)
        return self._signals

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


def _author_books(ctx: SearchContext, name: str) -> list[int]:
    """The best-matching author's books, most borrowed first."""
    matches = find_authors(ctx.conn, name, limit=1)
    if not matches:
        return []
    popularity = dict(zip(ctx.index.work_ids.tolist(), ctx.popularity.tolist(), strict=True))
    return sorted(matches[0].work_ids, key=lambda w: -popularity.get(w, 0.0))


def _seed_vector(index: DenseIndex, seeds: list[int]) -> np.ndarray | None:
    rows = np.isin(index.work_ids, seeds) & index.has_vector
    if not rows.any():
        return None
    vector = index.matrix[rows].mean(axis=0)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else None


def _near(
    index: DenseIndex, vector: np.ndarray, mask: np.ndarray, ignore: list[int] | None = None
) -> list[int]:
    hits = index.search(vector, CANDIDATES, allowed=mask, max_gap=MAX_GAP, ignore=ignore or [])
    return [h.work_id for h in hits]


def parsed_hybrid(ctx: SearchContext, query: str, k: int) -> list[int]:
    """The cascade parser's reading drives everything: its hard constraints filter; a lookup's
    title or author comes first; "like X" searches near the seed book (and leaves it out); the
    negation-stripped semantic text goes to BM25 and dense; RRF, then soft constraints nudge
    (`ranking.soft`). Dense hits far below the catalog's best match are dropped (`MAX_GAP`), so a
    filter that leaves only off-topic books shows none of them. An author named in a non-lookup ("neil gaiman for kids") narrows the
    search to their books."""
    request = ctx.parsed(query)
    embedder, index = ctx.require_dense()
    constraints = [*request.constraints, *ctx.extra_constraints]
    mask = allowed_mask(ctx.conn, constraints, ctx.index.work_ids)
    lookup = request.lookup
    author_books = _author_books(ctx, lookup.author) if lookup and lookup.author else []
    if author_books and request.intent != "lookup":
        mask = mask & np.isin(ctx.index.work_ids, author_books)

    rankings: list[list[int]] = []
    semantic = request.semantic_query.strip()
    if semantic:
        rankings.append([h.work_id for h in ctx.index.search(semantic, CANDIDATES, allowed=mask)])
        vector = embedder.encode_query(semantic)
        rankings.append(_near(index, vector, mask))
    if (seed := _seed_vector(index, request.seed_work_ids)) is not None:
        rankings.append(_near(index, seed, mask, ignore=request.seed_work_ids))
    if not rankings:  # nothing parsed out: fall back to the words as typed
        rankings.append([h.work_id for h in ctx.index.search(query, CANDIDATES, allowed=mask)])
        rankings.append(_near(index, embedder.encode_query(query), mask))

    signals = ctx.signals()
    scored = [
        (
            work_id,
            score
            + SOFT_WEIGHT
            * soft_score(
                constraints,
                signals.facets.get(work_id),
                signals.genres.get(work_id, []),
                signals.popularity_rank.get(work_id),
                signals.pages.get(work_id),
                signals.year.get(work_id),
            ),
        )
        for work_id, score in rrf(rankings)
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))

    known: list[int] = []
    if request.intent == "lookup" and lookup:
        if lookup.title:
            known += [m.work_id for m in find_titles(ctx.conn, lookup.title)]
        known += author_books
    allowed = _allowed_ids(ctx, mask)
    seeds = set(request.seed_work_ids)
    ranked = known + [w for w, _ in scored]
    return [w for w in dict.fromkeys(ranked) if w in allowed and w not in seeds][:k]


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
    "parsed_hybrid": parsed_hybrid,
}
DENSE_SYSTEMS = ("dense", "hybrid", "hybrid_lookup", "hybrid_rerank")
RERANK_SYSTEMS = ("hybrid_rerank",)
PARSED_SYSTEMS = ("parsed_hybrid",)
# Systems whose results go into the judging pool. Random adds labeling cost for little value.
# Rerank and parsed systems pool only when their model or parser is given (RERANKER=, PARSER=);
# otherwise their earlier pairs are kept, not dropped.
POOL_SYSTEMS = ("popular", "bm25_raw", "bm25", "bm25_lookup", *DENSE_SYSTEMS, *PARSED_SYSTEMS)


def available_systems(ctx: SearchContext, names: list[str]) -> list[str]:
    """Drop dense systems when no embedding model is loaded, rerank ones without a reranker,
    parsed ones without a parser (they are dense too)."""
    return [
        n
        for n in names
        if (ctx.dense is not None or n not in (*DENSE_SYSTEMS, *PARSED_SYSTEMS))
        and (ctx.reranker is not None or n not in RERANK_SYSTEMS)
        and (ctx.parser is not None or n not in PARSED_SYSTEMS)
    ]


def cascade_parser(
    conn: Connection, model: str | None = None, cache: Path = LLM_CACHE
) -> tuple[Parser, list[str]]:
    """The cascade parser behind the LLM answer cache, and the list it appends fallbacks to.
    Ollama is only contacted for queries not in the cache."""
    from shelfwise.llm.cache import CachedLLM
    from shelfwise.llm.client import OllamaClient
    from shelfwise.query.cascade import CascadeParser, CatalogLinker

    cascade = CascadeParser(CachedLLM(OllamaClient(model=model), cache), CatalogLinker(conn))
    fallbacks: list[str] = []

    def parse(query: str, today: date) -> ParsedRequest:
        result = cascade.parse(query, today)
        if not result.used_llm and not result.fast_path:
            fallbacks.append(query)
        return result.request

    return parse, fallbacks


def load_context(
    conn: Connection,
    embedding_model: str | None,
    today: date | None = None,
    reranker_model: str | None = None,
    parser: str | None = None,
) -> SearchContext:
    """Search context with the dense index when embeddings exist for the model; otherwise
    lexical-only, with a note (so scripts still run before `make embed`). A reranker is loaded
    only when named: it is the slowest model in the pipeline."""
    ctx = _load_context(conn, embedding_model, today, reranker_model)
    if parser == "cascade":
        ctx.parser, ctx.parse_fallbacks = cascade_parser(conn)
    elif parser is not None:
        raise ValueError(f"unknown parser {parser!r}; one of {PARSERS}")
    return ctx


def _load_context(
    conn: Connection, embedding_model: str | None, today: date | None, reranker_model: str | None
) -> SearchContext:
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
