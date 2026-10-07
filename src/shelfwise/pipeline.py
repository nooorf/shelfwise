"""The stateless search pipeline behind POST /api/v1/search (design doc §8, §20).

parse (rules) -> hard filters -> known-item lookup + hybrid retrieval -> live availability.

Indexes live in memory for the life of the process and are rebuilt when `catalog_version` changes,
so an import or merge shows up without a restart. Availability is always read live from the copy
table for the books returned, never from the index. Reranking, the LLM parser and narration
plug in here in later phases.
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
from shelfwise.evaluation.systems import SearchContext, bm25_lookup, hybrid_lookup
from shelfwise.query.constraints import contradictions
from shelfwise.query.rules import parse_rules
from shelfwise.retrieval.filters import relaxations

MAX_RELAXATIONS = 3


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
    catalog_version: int
    constraints: list[ParsedConstraint]
    residual: str  # what was searched for after removing filter phrases
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
    ) -> None:
        self.embedder = embedder
        self.today = today
        self._ctx: SearchContext | None = None
        self._version: int | None = None
        self._lock = threading.Lock()

    def _context(self, conn: Connection) -> SearchContext:
        version = get_catalog_version(conn)
        with self._lock:
            if self._ctx is None or version != self._version:
                self._ctx = SearchContext.build(conn, embedder=self.embedder)
                self._version = version
            ctx = self._ctx
        return replace(ctx, conn=conn, today=self.today())  # per-request connection and date

    def search(self, conn: Connection, request: SearchRequest) -> SearchResponse:
        timings: dict[str, float] = {}
        start = clock = time.perf_counter()

        def lap(stage: str) -> None:
            nonlocal clock
            now = time.perf_counter()
            timings[stage] = round((now - clock) * 1000, 1)
            clock = now

        ctx = self._context(conn)
        lap("index")
        parse = parse_rules(request.query, ctx.today)
        conflicts = contradictions(parse.constraints)
        lap("parse")
        system = hybrid_lookup if ctx.dense is not None else bm25_lookup
        ids = [] if conflicts else system(ctx, request.query, request.limit)
        lap("retrieve")
        results = self._details(conn, ids, ctx.today)
        lap("details")
        relaxed = []
        if not ids and not conflicts and any(c.strength == "hard" for c in parse.constraints):
            relaxed = [
                Relaxation(drop=r.label, count=r.count)
                for r in relaxations(conn, parse.constraints)[:MAX_RELAXATIONS]
                if r.count
            ]
            lap("relax")
        timings["total"] = round((time.perf_counter() - start) * 1000, 1)

        return SearchResponse(
            query=request.query,
            system=system.__name__,
            catalog_version=self._version or 0,
            constraints=[
                ParsedConstraint(**c.model_dump(include=set(ParsedConstraint.model_fields)))
                for c in parse.constraints
            ],
            residual=parse.residual,
            contradictions=[c.message() for c in conflicts],
            results=results,
            relaxations=relaxed,
            timings_ms=timings,
        )

    def _details(self, conn: Connection, ids: list[int], today: date) -> list[BookResult]:
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


def build_service(embedding_model: str | None, conn: Connection) -> SearchService:
    """Hybrid search when `embedding_model` has stored embeddings; keyword-only otherwise."""
    if embedding_model:
        stored = conn.execute(
            text("SELECT count(*) FROM work_embedding WHERE model_name = :m"),
            {"m": embedding_model},
        ).scalar_one()
        if stored:
            from shelfwise.embed.encoder import load_embedder

            return SearchService(embedder=load_embedder(embedding_model))
    return SearchService()
