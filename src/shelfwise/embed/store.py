"""Keep work.search_text and work_embedding up to date.

`refresh_search_text` rebuilds each work's text and content hash; `embed_missing` encodes only
works whose (content hash, model) pair has no embedding yet. Editing one description re-embeds one
book; circulation changes never re-embed anything.
"""

from collections.abc import Callable

from sqlalchemy import Connection, bindparam, text, update
from sqlalchemy.dialects.postgresql import insert

from shelfwise.catalog import schema
from shelfwise.embed.encoder import Embedder
from shelfwise.embed.text_builder import build_search_text, content_hash

_WORK_TEXT_SQL = text(
    """
    SELECT w.work_id, w.title, w.subtitle, w.genres, w.themes, w.tags, w.description,
           w.content_hash,
           coalesce((SELECT array_agg(a.display ORDER BY wa.position)
                       FROM work_author wa JOIN author a USING (author_id)
                      WHERE wa.work_id = w.work_id), '{}') AS authors
    FROM work w
    ORDER BY w.work_id
    """
)


def refresh_search_text(conn: Connection) -> int:
    """Rebuild search_text/content_hash; returns how many works changed."""
    changes = []
    for r in conn.execute(_WORK_TEXT_SQL):
        search_text = build_search_text(
            r.title, r.subtitle, r.authors, r.genres, r.themes, r.tags, r.description
        )
        digest = content_hash(search_text)
        if digest != r.content_hash:
            changes.append({"wid": r.work_id, "st": search_text, "h": digest})
    if changes:
        conn.execute(
            update(schema.work)
            .where(schema.work.c.work_id == bindparam("wid"))
            .values(search_text=bindparam("st"), content_hash=bindparam("h")),
            changes,
        )
    return len(changes)


def embed_missing(
    conn: Connection,
    embedder: Embedder,
    batch_size: int = 64,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Embed works with no embedding for this model at their current content hash."""
    rows = conn.execute(
        text(
            """
            SELECT w.work_id, w.search_text, w.content_hash
            FROM work w
            LEFT JOIN work_embedding e
                   ON e.work_id = w.work_id AND e.model_name = :model
            WHERE w.search_text IS NOT NULL
              AND (e.work_id IS NULL OR e.content_hash <> w.content_hash)
            ORDER BY w.work_id
            """
        ),
        {"model": embedder.name},
    ).all()
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = embedder.encode_documents([r.search_text for r in batch])
        stmt = insert(schema.work_embedding).values(
            [
                {
                    "work_id": r.work_id,
                    "model_name": embedder.name,
                    "content_hash": r.content_hash,
                    "dim": int(vector.shape[0]),
                    "embedding": vector,
                }
                for r, vector in zip(batch, vectors, strict=True)
            ]
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["work_id", "model_name"],
                set_={
                    "content_hash": stmt.excluded.content_hash,
                    "dim": stmt.excluded.dim,
                    "embedding": stmt.excluded.embedding,
                    "created_at": stmt.excluded.created_at,
                },
            )
        )
        if progress:
            progress(min(start + batch_size, len(rows)), len(rows))
    return len(rows)
