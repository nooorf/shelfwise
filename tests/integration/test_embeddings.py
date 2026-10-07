from datetime import date

import numpy as np
import pytest
from sqlalchemy import Connection, func, insert, select, update

from shelfwise.catalog import schema
from shelfwise.embed.store import embed_missing, refresh_search_text
from shelfwise.evaluation.systems import (
    SYSTEMS,
    SearchContext,
    available_systems,
    dense,
    hybrid,
    hybrid_lookup,
    hybrid_rerank,
)
from shelfwise.ranking.rerank import CachedReranker
from shelfwise.retrieval.dense import DenseIndex

from ..fakes import FakeEmbedder, FakeReranker
from .factories import add_author, add_copy, add_edition, add_work

BOOKS = [
    ("The Silent Patient", "Alex Michaelides", 336, "a dark psychological thriller about a silent painter"),
    ("Murder at the Vicarage", "Agatha Christie", 288, "a cozy village mystery with a vicar"),
    ("Dune", "Frank Herbert", 412, "a desert planet, spice and a space opera adventure"),
    ("Sharp Objects", "Gillian Flynn", 254, "a dark psychological story of a journalist going home"),
]  # fmt: skip


@pytest.fixture
def catalog(conn: Connection) -> dict[str, int]:
    ids = {}
    for title, author, pages, description in BOOKS:
        work_id = add_work(conn, title)
        conn.execute(
            update(schema.work)
            .where(schema.work.c.work_id == work_id)
            .values(description=description)
        )
        add_copy(conn, add_edition(conn, work_id, pages=pages), "available")
        conn.execute(
            insert(schema.work_author).values(work_id=work_id, author_id=add_author(conn, author))
        )
        ids[title] = work_id
    return ids


def embedding_count(conn: Connection, model: str) -> int:
    return conn.execute(
        select(func.count())
        .select_from(schema.work_embedding)
        .where(schema.work_embedding.c.model_name == model)
    ).scalar_one()


def test_only_changed_books_are_re_embedded(conn: Connection, catalog: dict[str, int]) -> None:
    embedder = FakeEmbedder()

    assert refresh_search_text(conn) == len(BOOKS)
    assert embed_missing(conn, embedder) == len(BOOKS)
    assert refresh_search_text(conn) == 0
    assert embed_missing(conn, embedder) == 0

    conn.execute(
        update(schema.work)
        .where(schema.work.c.work_id == catalog["Dune"])
        .values(description="an epic of a desert world")
    )
    assert refresh_search_text(conn) == 1
    assert embed_missing(conn, embedder) == 1
    assert embedding_count(conn, "fake") == len(BOOKS)


def test_models_are_stored_side_by_side(conn: Connection, catalog: dict[str, int]) -> None:
    refresh_search_text(conn)
    embed_missing(conn, FakeEmbedder("small", dim=16))
    embed_missing(conn, FakeEmbedder("large", dim=64))

    assert embedding_count(conn, "small") == embedding_count(conn, "large") == len(BOOKS)


def test_dense_index_loads_aligned_to_given_order(
    conn: Connection, catalog: dict[str, int]
) -> None:
    refresh_search_text(conn)
    embed_missing(conn, FakeEmbedder())
    order = np.array([catalog["Dune"], catalog["The Silent Patient"], 999_999])

    index = DenseIndex.load(conn, "fake", order)

    assert index.has_vector.tolist() == [True, True, False]
    with pytest.raises(LookupError):
        DenseIndex.load(conn, "never-embedded", order)


@pytest.fixture
def ctx(conn: Connection, catalog: dict[str, int]) -> SearchContext:
    refresh_search_text(conn)
    embedder = FakeEmbedder()
    embed_missing(conn, embedder)
    return SearchContext.build(conn, today=date(2026, 10, 6), embedder=embedder)


def test_dense_finds_meaning_and_respects_filters(
    ctx: SearchContext, catalog: dict[str, int]
) -> None:
    top = dense(ctx, "something dark and psychological", 2)
    assert set(top) == {catalog["The Silent Patient"], catalog["Sharp Objects"]}

    short_only = dense(ctx, "something dark and psychological under 300 pages", 5)
    assert catalog["The Silent Patient"] not in short_only  # 336 pages
    assert short_only[0] == catalog["Sharp Objects"]


def test_dense_embeds_the_residual_not_the_filter_words(ctx: SearchContext) -> None:
    assert ctx.embedder is not None
    dense(ctx, "dark thriller under 300 pages published after 2015", 3)

    assert ctx.embedder.queries[-1] == "dark thriller"  # type: ignore[attr-defined]


def test_hybrid_combines_both_channels(ctx: SearchContext, catalog: dict[str, int]) -> None:
    top = hybrid(ctx, "dark psychological", 4)

    assert set(top[:2]) == {catalog["The Silent Patient"], catalog["Sharp Objects"]}
    assert hybrid_lookup(ctx, "do you have dune", 1) == [catalog["Dune"]]


def test_dense_systems_need_an_embedder(conn: Connection, catalog: dict[str, int]) -> None:
    lexical_only = SearchContext.build(conn, today=date(2026, 10, 6))

    with pytest.raises(RuntimeError, match="embedding model"):
        dense(lexical_only, "anything", 3)


def test_rerank_respects_filters_and_needs_a_reranker(
    conn: Connection, catalog: dict[str, int]
) -> None:
    embedder = FakeEmbedder()
    refresh_search_text(conn)
    embed_missing(conn, embedder)
    plain = SearchContext.build(conn, today=date(2026, 10, 6), embedder=embedder)
    with_reranker = SearchContext.build(
        conn, today=date(2026, 10, 6), embedder=embedder, reranker=CachedReranker(FakeReranker())
    )

    assert "hybrid_rerank" not in available_systems(plain, list(SYSTEMS))
    with pytest.raises(RuntimeError, match="reranker"):
        hybrid_rerank(plain, "anything", 3)
    top = hybrid_rerank(with_reranker, "dark psychological story under 300 pages", 4)
    assert set(top) == {catalog["Sharp Objects"], catalog["Murder at the Vicarage"]}  # < 300 pp
    assert top[0] == catalog["Sharp Objects"]  # the reranker prefers the dark psychological one
