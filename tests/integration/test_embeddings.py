from dataclasses import replace
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
    parsed_hybrid,
)
from shelfwise.query.constraints import Constraint, Op, Strength
from shelfwise.query.request import LookupSpec, ParsedRequest
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


def constraint(field: str, op: Op, value: object, strength: Strength = "hard") -> Constraint:
    return Constraint(field=field, op=op, value=value, strength=strength, source="llm")


def with_parses(ctx: SearchContext, parses: dict[str, ParsedRequest]) -> SearchContext:
    return replace(ctx, parser=lambda query, today: parses[query], _parses={})


def test_parsed_systems_need_a_parser(ctx: SearchContext) -> None:
    assert "parsed_hybrid" not in available_systems(ctx, list(SYSTEMS))
    with pytest.raises(RuntimeError, match="parser"):
        parsed_hybrid(ctx, "anything", 3)


def test_parsed_hybrid_filters_and_searches_the_stripped_text(
    ctx: SearchContext, catalog: dict[str, int]
) -> None:
    query = "dark psychological, nothing over 300 pages, no space stuff"
    parsed = with_parses(ctx, {query: ParsedRequest(
        intent="discover",
        semantic_query="dark psychological",
        constraints=[constraint("pages", "lt", 300)],
    )})  # fmt: skip

    top = parsed_hybrid(parsed, query, 4)

    assert top[0] == catalog["Sharp Objects"]
    assert catalog["The Silent Patient"] not in top  # 336 pages
    assert ctx.embedder is not None
    assert ctx.embedder.queries[-1] == "dark psychological"  # type: ignore[attr-defined]


def test_parsed_hybrid_lookups_seeds_and_authors(
    ctx: SearchContext, catalog: dict[str, int]
) -> None:
    parsed = with_parses(ctx, {
        "got dune?": ParsedRequest(intent="lookup", lookup=LookupSpec(title="Dune")),
        "like the silent patient": ParsedRequest(
            intent="similar",
            seed_titles=["The Silent Patient"],
            seed_work_ids=[catalog["The Silent Patient"]],
        ),
        "agatha christie, something cozy": ParsedRequest(
            intent="discover", semantic_query="cozy", lookup=LookupSpec(author="Agatha Christie")
        ),
    })  # fmt: skip

    assert parsed_hybrid(parsed, "got dune?", 1) == [catalog["Dune"]]
    similar = parsed_hybrid(parsed, "like the silent patient", 4)
    assert catalog["The Silent Patient"] not in similar  # the seed itself isn't a suggestion
    assert similar[0] == catalog["Sharp Objects"]
    assert parsed_hybrid(parsed, "agatha christie, something cozy", 4) == [
        catalog["Murder at the Vicarage"]
    ]


def test_an_author_lookup_with_a_preference_ranks_their_books_by_it(
    conn: Connection, catalog: dict[str, int]
) -> None:
    vicarage = catalog["Murder at the Vicarage"]
    author = conn.execute(
        select(schema.work_author.c.author_id).where(schema.work_author.c.work_id == vicarage)
    ).scalar_one()
    styles = add_work(conn, "The Mysterious Affair at Styles")
    conn.execute(
        update(schema.work)
        .where(schema.work.c.work_id == styles)
        .values(description="a country house murder and a Belgian detective", popularity=0.9)
    )
    add_copy(conn, add_edition(conn, styles, pages=296), "available")
    conn.execute(insert(schema.work_author).values(work_id=styles, author_id=author))
    for work_id, audience in ((vicarage, "children"), (styles, "adult")):
        conn.execute(
            insert(schema.work_facets).values(work_id=work_id, audience=audience, source="human")
        )
    refresh_search_text(conn)
    embedder = FakeEmbedder()
    embed_missing(conn, embedder)
    ctx = SearchContext.build(conn, today=date(2026, 10, 6), embedder=embedder)
    by_christie = ParsedRequest(intent="lookup", lookup=LookupSpec(author="Agatha Christie"))
    for_kids = by_christie.model_copy(
        update={"constraints": [constraint("facet.audience", "eq", "children", "soft")]}
    )
    parsed = with_parses(ctx, {"agatha christie": by_christie, "christie for kids": for_kids})

    # Just the author: most borrowed first. With "for kids": the kids' book first, theirs only.
    assert parsed_hybrid(parsed, "agatha christie", 4)[:2] == [styles, vicarage]
    assert parsed_hybrid(parsed, "christie for kids", 4) == [vicarage, styles]


def test_soft_constraints_move_books_without_removing_any(
    conn: Connection, ctx: SearchContext, catalog: dict[str, int]
) -> None:
    for title, darkness in (("Murder at the Vicarage", 0), ("Sharp Objects", 3)):
        conn.execute(
            insert(schema.work_facets).values(
                work_id=catalog[title], darkness=darkness, source="human"
            )
        )
    plain = ParsedRequest(intent="discover", semantic_query="a story")
    cozy = plain.model_copy(
        update={"constraints": [constraint("facet.darkness", "lte", 1, "soft")]}
    )
    parsed = with_parses(ctx, {"plain": plain, "cozy": cozy})

    without, with_soft = parsed_hybrid(parsed, "plain", 4), parsed_hybrid(parsed, "cozy", 4)

    assert set(with_soft) == set(without)
    assert with_soft.index(catalog["Murder at the Vicarage"]) < with_soft.index(
        catalog["Sharp Objects"]
    )
