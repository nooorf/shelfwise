"""Retrieval systems under evaluation, all with the same signature (design doc §29).

Each takes a query and returns ranked work ids. New systems (dense, hybrid, reranked) register
here, and the pooling and evaluation scripts pick them up by name.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import Connection, text

from shelfwise.query.rules import parse_rules
from shelfwise.retrieval.filters import allowed_mask
from shelfwise.retrieval.lexical import LexicalIndex, build_lexical_index
from shelfwise.retrieval.lookup import find_authors, find_by_isbn, find_titles


@dataclass
class SearchContext:
    conn: Connection
    index: LexicalIndex
    popularity: np.ndarray  # aligned with index.work_ids
    today: date

    @classmethod
    def build(cls, conn: Connection, today: date | None = None) -> "SearchContext":
        index = build_lexical_index(conn)
        pop = {
            r.work_id: r.popularity
            for r in conn.execute(text("SELECT work_id, popularity FROM work"))
        }
        popularity = np.array([pop.get(int(w), 0.0) for w in index.work_ids], dtype=np.float64)
        return cls(conn, index, popularity, today or date.today())

    def mask(self, query: str) -> tuple[np.ndarray, str]:
        parse = parse_rules(query, self.today)
        return allowed_mask(self.conn, parse.constraints, self.index.work_ids), parse.residual


System = Callable[[SearchContext, str, int], list[int]]


def bm25_raw(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Keyword search on the raw query, no parsing, no filters (the OPAC-style floor)."""
    return [h.work_id for h in ctx.index.search(query, k)]


def bm25(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Rule parser -> hard filters -> BM25 on the residual text."""
    mask, residual = ctx.mask(query)
    return [h.work_id for h in ctx.index.search(residual, k, allowed=mask)]


def bm25_lookup(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Known-item lookups first (ISBN, title, author's books by popularity), then BM25."""
    mask, residual = ctx.mask(query)
    allowed = {int(w) for w, ok in zip(ctx.index.work_ids, mask, strict=True) if ok}
    popularity = dict(zip(ctx.index.work_ids.tolist(), ctx.popularity.tolist(), strict=True))
    ranked: list[int] = []
    ranked += find_by_isbn(ctx.conn, query)
    ranked += [m.work_id for m in find_titles(ctx.conn, query)]
    for author in find_authors(ctx.conn, query):
        ranked += sorted(author.work_ids, key=lambda w: -popularity.get(w, 0.0))
    ranked += [h.work_id for h in ctx.index.search(residual, k * 2, allowed=mask)]
    return [w for w in dict.fromkeys(ranked) if w in allowed][:k]


def popular(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Most-borrowed works that pass the hard filters; ignores the query's meaning."""
    mask, _ = ctx.mask(query)
    order = np.argsort(-np.where(mask, ctx.popularity, -1.0), kind="stable")
    return [int(ctx.index.work_ids[i]) for i in order[:k] if mask[i]]


def random_filtered(ctx: SearchContext, query: str, k: int) -> list[int]:
    """Uniform sample of works that pass the hard filters (seeded by the query)."""
    mask, _ = ctx.mask(query)
    candidates = [int(w) for w, ok in zip(ctx.index.work_ids, mask, strict=True) if ok]
    return random.Random(query).sample(candidates, min(k, len(candidates)))


SYSTEMS: dict[str, System] = {
    "random": random_filtered,
    "popular": popular,
    "bm25_raw": bm25_raw,
    "bm25": bm25,
    "bm25_lookup": bm25_lookup,
}
# Systems whose results go into the judging pool. Random adds labeling cost for little value.
POOL_SYSTEMS = ("popular", "bm25_raw", "bm25", "bm25_lookup")
