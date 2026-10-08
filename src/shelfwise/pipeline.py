"""The stateless search pipeline behind POST /api/v1/search (design doc §8, §20).

parse (cascade: rules + LLM) -> hard filters -> lookups, seeds, hybrid retrieval, soft-constraint
nudge (`parsed_hybrid`) -> live availability.

Without an LLM, or when it is down or answers badly, the parse is rules-only and retrieval is the
rules-era `hybrid_lookup` (or `hybrid_rerank` with a reranker, `bm25_lookup` without embeddings):
those find known items from the raw query, which a rules-only parse can't name. The response
says which parser answered and why it fell back.

Indexes live in memory for the life of the process and are rebuilt when `catalog_version` changes,
so an import or merge shows up without a restart. Availability is always read live from the copy
table for the books returned, never from the index. Conversation state and narration plug in
here next (Phase 4).
"""

import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from shelfwise.catalog.availability import AvailabilityState, fetch_live_availability
from shelfwise.catalog.meta import get_catalog_version
from shelfwise.embed.encoder import Embedder
from shelfwise.evaluation.judgments import work_keys
from shelfwise.evaluation.systems import (
    SearchContext,
    bm25_lookup,
    hybrid_lookup,
    hybrid_rerank,
    parsed_hybrid,
)
from shelfwise.llm.client import StructuredLLM
from shelfwise.query.cascade import CascadeParser, CatalogLinker
from shelfwise.query.constraints import Constraint, contradictions
from shelfwise.query.request import Intent, LookupSpec, ParsedRequest, from_rules
from shelfwise.query.rules import parse_rules
from shelfwise.ranking.rerank import CachedReranker
from shelfwise.retrieval.filters import relaxations

MAX_RELAXATIONS = 3
PARSE_TIMEOUT_S = 20.0  # a slow LLM costs one fallback to the rules, not a hung request


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class ParsedConstraint(BaseModel):
    field: str
    op: str
    value: Any
    strength: str
    polarity: str
    span: str | None


class Location(BaseModel):
    branch: str
    floor: str | None
    call_number: str | None


class Availability(BaseModel):
    state: AvailabilityState
    available_copies: int
    total_copies: int
    next_due: date | None
    location: Location | None  # where to find a copy: an available one if there is one


class BookResult(BaseModel):
    work_id: int
    work_key: str  # lowest ISBN-13: stable across catalog rebuilds
    title: str
    subtitle: str | None
    authors: list[str]
    year: int | None
    pages: int | None
    genres: list[str]
    availability: Availability


class Relaxation(BaseModel):
    drop: str  # the words of the constraint to drop, e.g. "under 100 pages"
    count: int  # how many books match without it


class SearchResponse(BaseModel):
    query: str
    system: str  # which retrieval system answered (changes as the pipeline grows)
    parser: str  # "cascade" (rules + LLM) or "rules"
    parse_error: str | None  # why the LLM step was skipped, when it was
    intent: Intent
    lookup: LookupSpec | None  # the book or author asked for, catalog spelling
    seed_titles: list[str]  # "like X": the reference books
    catalog_version: int
    constraints: list[ParsedConstraint]
    residual: str  # what was searched for: negated words and filter phrases removed
    contradictions: list[str]
    results: list[BookResult]
    relaxations: list[Relaxation]  # only when nothing matched every hard constraint
    timings_ms: dict[str, float]


_DETAILS_SQL = text(
    """
    SELECT w.work_id, w.title, w.subtitle, w.first_pub_year, w.genres,
           coalesce((SELECT array_agg(a.display ORDER BY wa.position)
                       FROM work_author wa JOIN author a USING (author_id)
                      WHERE wa.work_id = w.work_id), '{}') AS authors,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages
    FROM work w WHERE w.work_id = ANY(:ids)
    """
)
# One copy per work to point the reader at: available first, then on the shelf for reference,
# then any; lowest call number for a stable answer.
_LOCATION_SQL = text(
    """
    SELECT DISTINCT ON (e.work_id) e.work_id, c.branch, c.floor, c.call_number
    FROM edition e JOIN copy c USING (edition_id)
    WHERE e.work_id = ANY(:ids) AND c.status <> 'lost'
    ORDER BY e.work_id,
             CASE c.status WHEN 'available' THEN 0 WHEN 'reference_only' THEN 1 ELSE 2 END,
             c.call_number
    """
)


class SearchService:
    """One per process. Thread-safe: requests share the read-only indexes."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        today: Callable[[], date] = date.today,
        reranker: CachedReranker | None = None,
        llm: StructuredLLM | None = None,
    ) -> None:
        self.embedder = embedder
        self.reranker = reranker
        self.llm = llm
        self.today = today
        self._ctx: SearchContext | None = None
        self._version: int | None = None
        self._lock = threading.Lock()

    @property
    def catalog_version(self) -> int:
        return self._version or 0

    def context(self, conn: Connection) -> SearchContext:
        version = get_catalog_version(conn)
        with self._lock:
            if self._ctx is None or version != self._version:
                self._ctx = SearchContext.build(
                    conn, embedder=self.embedder, reranker=self.reranker
                )
                self._ctx.signals()  # facets etc. once per catalog version, shared by requests
                self._version = version
            ctx = self._ctx
        return replace(ctx, conn=conn, today=self.today())  # per-request connection and date

    def retrieve(
        self, ctx: SearchContext, query: str, parsed: ParsedRequest, use_parse: bool, limit: int
    ) -> tuple[str, list[int]]:
        """Which system answers and its ranked work ids. `use_parse`: retrieve from `parsed`
        (`parsed_hybrid`); otherwise from the raw `query` with the rules-era systems, which
        find known items a rules-only parse can't name (see the module docstring)."""
        if contradictions(parsed.constraints):
            return "none", []
        if ctx.dense is None:
            system = bm25_lookup
        elif use_parse:
            system = parsed_hybrid
            ctx = replace(ctx, parser=lambda _query, _today: parsed, _parses={})
        else:
            system = hybrid_rerank if ctx.reranker is not None else hybrid_lookup
        return system.__name__, system(ctx, query, limit)

    def relax(self, conn: Connection, constraints: list[Constraint]) -> list[Relaxation]:
        """When nothing matched: which hard constraint to drop, and how many books that gives."""
        if not any(c.strength == "hard" for c in constraints) or contradictions(constraints):
            return []
        return [
            Relaxation(drop=r.label, count=r.count)
            for r in relaxations(conn, constraints)[:MAX_RELAXATIONS]
            if r.count
        ]

    def search(self, conn: Connection, request: SearchRequest) -> SearchResponse:
        timings: dict[str, float] = {}
        start = clock = time.perf_counter()

        def lap(stage: str) -> None:
            nonlocal clock
            now = time.perf_counter()
            timings[stage] = round((now - clock) * 1000, 1)
            clock = now

        ctx = self.context(conn)
        lap("index")
        parsed, parse_error = self.parse(conn, request.query, ctx)
        constraints = parsed.constraints
        conflicts = contradictions(constraints)
        lap("parse")
        use_parse = parse_error is None and self.llm is not None
        system, ids = self.retrieve(ctx, request.query, parsed, use_parse, request.limit)
        lap("retrieve")
        results = self.details(conn, ids, ctx.today)
        lap("details")
        relaxed = [] if ids else self.relax(conn, constraints)
        lap("relax")
        timings["total"] = round((time.perf_counter() - start) * 1000, 1)

        return SearchResponse(
            query=request.query,
            system=system,
            parser="rules" if parse_error is not None or self.llm is None else "cascade",
            parse_error=parse_error,
            intent=parsed.intent,
            lookup=parsed.lookup,
            seed_titles=parsed.seed_titles,
            catalog_version=self._version or 0,
            constraints=[
                ParsedConstraint(**c.model_dump(include=set(ParsedConstraint.model_fields)))
                for c in constraints
            ],
            residual=parsed.semantic_query,
            contradictions=[c.message() for c in conflicts],
            results=results,
            relaxations=relaxed,
            timings_ms=timings,
        )

    def parse(
        self, conn: Connection, query: str, ctx: SearchContext
    ) -> tuple[ParsedRequest, str | None]:
        """The cascade's parse, or the rules' with the reason the LLM step didn't count."""
        if self.llm is None:
            return from_rules(parse_rules(query, ctx.today)), None
        if ctx.dense is None:
            return from_rules(parse_rules(query, ctx.today)), "no embeddings: keyword search only"
        result = CascadeParser(self.llm, CatalogLinker(conn)).parse(query, ctx.today)
        return result.request, result.error

    def details(self, conn: Connection, ids: list[int], today: date) -> list[BookResult]:
        if not ids:
            return []
        rows = {r.work_id: r for r in conn.execute(_DETAILS_SQL, {"ids": ids})}
        places = {r.work_id: r for r in conn.execute(_LOCATION_SQL, {"ids": ids})}
        live = fetch_live_availability(conn, ids)
        keys = work_keys(conn, ids)
        results = []
        for work_id in ids:
            row, place, availability = rows[work_id], places.get(work_id), live[work_id]
            results.append(
                BookResult(
                    work_id=work_id,
                    work_key=keys[work_id],
                    title=row.title,
                    subtitle=row.subtitle,
                    authors=list(row.authors),
                    year=row.first_pub_year,
                    pages=row.pages,
                    genres=list(row.genres),
                    availability=Availability(
                        state=availability.state(today),
                        available_copies=availability.available_copies,
                        total_copies=availability.total_copies,
                        next_due=availability.next_due,
                        location=Location(
                            branch=place.branch, floor=place.floor, call_number=place.call_number
                        )
                        if place
                        else None,
                    ),
                )
            )
        return results


def build_service(
    embedding_model: str | None,
    conn: Connection,
    rerank_model: str | None = None,
    llm_model: str | None = None,
) -> SearchService:
    """Hybrid search when `embedding_model` has stored embeddings, keyword-only otherwise; the
    reranker only on top of rules-era hybrid; the LLM parser (`llm_model`) only with embeddings.
    Ollama is contacted per request, so the service starts even when it isn't running."""
    if embedding_model:
        stored = conn.execute(
            text("SELECT count(*) FROM work_embedding WHERE model_name = :m"),
            {"m": embedding_model},
        ).scalar_one()
        if stored:
            from shelfwise.embed.encoder import load_embedder
            from shelfwise.ranking.rerank import load_reranker

            reranker = load_reranker(rerank_model) if rerank_model else None
            llm = None
            if llm_model:
                from shelfwise.llm.client import OllamaClient

                llm = OllamaClient(model=llm_model, timeout=PARSE_TIMEOUT_S)
            return SearchService(
                embedder=load_embedder(embedding_model), reranker=reranker, llm=llm
            )
    return SearchService()
