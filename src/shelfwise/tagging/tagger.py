"""Tag every book that has no tags from the current prompt version and model.

Human labels (source='human') are never overwritten. Each book is its own small transaction, so a
long overnight run can be stopped and resumed without losing work. A book whose output fails
validation twice is logged to `ingest_error` and skipped.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, insert, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shelfwise.catalog import schema
from shelfwise.llm.client import LLMInvalidOutput, StructuredLLM
from shelfwise.tagging.facets import (
    BookFacets,
    BookFacetsLLM,
    BookRecord,
    apply_consistency_rules,
    apply_record_rules,
    build_messages,
    model_version,
    normalize_themes,
)


@dataclass
class TagRunStats:
    tagged: int = 0
    failed: int = 0
    seconds: float = 0.0
    completion_tokens: int = 0


_UNTAGGED_SQL = text(
    """
    SELECT w.work_id, w.title, w.genres, w.tags, w.description, w.first_pub_year,
           coalesce((SELECT array_agg(a.display ORDER BY wa.position)
                       FROM work_author wa JOIN author a USING (author_id)
                      WHERE wa.work_id = w.work_id), '{}') AS authors
    FROM work w
    LEFT JOIN work_facets f ON f.work_id = w.work_id
    WHERE (f.work_id IS NULL
           OR (f.source = 'llm' AND f.model_version IS DISTINCT FROM :version))
      AND (CAST(:only AS bigint[]) IS NULL OR w.work_id = ANY(:only))
    ORDER BY w.work_id
    LIMIT :limit
    """
)


def books_to_tag(
    conn: Connection, version: str, limit: int | None = None, only: list[int] | None = None
) -> list[BookRecord]:
    rows = conn.execute(
        _UNTAGGED_SQL, {"version": version, "limit": limit or 1_000_000, "only": only}
    )
    return [
        BookRecord(r.work_id, r.title, r.authors, r.genres, r.tags, r.description, r.first_pub_year)
        for r in rows
    ]


def save_facets(conn: Connection, work_id: int, facets: BookFacets, version: str) -> None:
    facets = apply_consistency_rules(facets)
    values = facets.model_dump(exclude={"themes"})
    stmt = pg_insert(schema.work_facets).values(
        work_id=work_id, source="llm", model_version=version, **values
    )
    conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["work_id"],
            set_={**{k: stmt.excluded[k] for k in values}, "model_version": version,
                  "tagged_at": stmt.excluded.tagged_at},
            where=schema.work_facets.c.source == "llm",  # never overwrite a human label
        )
    )  # fmt: skip
    conn.execute(
        update(schema.work)
        .where(schema.work.c.work_id == work_id)
        .values(themes=normalize_themes(facets.themes))
    )


def tag_books(
    engine: Engine,
    llm: StructuredLLM,
    limit: int | None = None,
    progress: Callable[[int, int, BookRecord], None] | None = None,
    only: list[int] | None = None,
) -> TagRunStats:
    """`only`: just these works (e.g. the hand-labelled ones, to score a prompt first)."""
    version = model_version(llm.model)
    with engine.connect() as conn:
        books = books_to_tag(conn, version, limit, only)
    stats = TagRunStats()
    for i, book in enumerate(books, start=1):
        try:
            result = llm.chat_structured(build_messages(book), BookFacetsLLM, max_tokens=300)
        except LLMInvalidOutput as exc:
            with engine.begin() as conn:
                conn.execute(
                    insert(schema.ingest_error).values(
                        source=f"tagging:{version}",
                        record_ref=str(book.work_id),
                        reason=str(exc)[:500],
                    )
                )
            stats.failed += 1
        else:
            with engine.begin() as conn:
                facets = apply_record_rules(result.value.to_facets(), book)
                save_facets(conn, book.work_id, facets, version)
            stats.tagged += 1
            stats.seconds += result.stats.total_ms / 1000
            stats.completion_tokens += result.stats.completion_tokens
        if progress:
            progress(i, len(books), book)
    return stats
