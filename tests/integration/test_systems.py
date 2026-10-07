from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import Connection, insert, update

from shelfwise.catalog import schema
from shelfwise.evaluation.judgments import work_keys
from shelfwise.evaluation.negation import Violation
from shelfwise.evaluation.negation_study import facet_filter
from shelfwise.evaluation.systems import (
    SYSTEMS,
    SearchContext,
    available_systems,
    bm25_lookup,
    popular,
)

from .factories import add_author, add_copy, add_edition, add_work


@pytest.fixture
def ctx(conn: Connection) -> SearchContext:
    books = [
        ("The Silent Patient", "Alex Michaelides", 2019, 336, 0.9),
        ("Gone Girl", "Gillian Flynn", 2012, 432, 0.7),
        ("Sharp Objects", "Gillian Flynn", 2006, 254, 0.4),
        ("The Haunting of Hill House", "Shirley Jackson", 1959, 246, 0.2),
    ]
    author_ids: dict[str, int] = {}
    for title, author, year, pages, popularity in books:
        work_id = add_work(conn, title, first_pub_year=year, genres=["thriller"])
        conn.execute(
            update(schema.work)
            .where(schema.work.c.work_id == work_id)
            .values(popularity=popularity, description=f"{title}: a dark psychological story")
        )
        add_copy(conn, add_edition(conn, work_id, pages=pages, isbn13=None), "available")
        if author not in author_ids:
            author_ids[author] = add_author(conn, author)
        conn.execute(
            insert(schema.work_author).values(work_id=work_id, author_id=author_ids[author])
        )
    return SearchContext.build(conn, today=date(2026, 10, 6))


def titles(conn: Connection, ids: list[int]) -> list[str]:
    rows = dict(
        (r.work_id, r.title)
        for r in conn.execute(schema.work.select().where(schema.work.c.work_id.in_(ids)))
    )
    return [rows[i] for i in ids]


FILTERED_QUERY = "a dark thriller under 300 pages published after 2000"


def test_every_filtered_system_respects_hard_filters(conn: Connection, ctx: SearchContext) -> None:
    for name in available_systems(ctx, list(SYSTEMS)):  # dense ones: test_embeddings.py
        system = SYSTEMS[name]
        if name == "bm25_raw":
            continue  # the deliberately unfiltered keyword baseline
        assert set(titles(conn, system(ctx, FILTERED_QUERY, 10))) <= {"Sharp Objects"}, name


def test_raw_baseline_ignores_filters(conn: Connection, ctx: SearchContext) -> None:
    assert len(SYSTEMS["bm25_raw"](ctx, FILTERED_QUERY, 10)) > 1


def test_lookup_puts_the_named_book_first(conn: Connection, ctx: SearchContext) -> None:
    assert (
        titles(conn, bm25_lookup(ctx, "do you have the silent pateint", 3))[0]
        == "The Silent Patient"
    )


def test_author_lookup_lists_their_books_by_popularity(
    conn: Connection, ctx: SearchContext
) -> None:
    assert titles(conn, bm25_lookup(ctx, "anything by gillian flynn", 2)) == [
        "Gone Girl",
        "Sharp Objects",
    ]


def test_popular_ignores_meaning_but_not_filters(conn: Connection, ctx: SearchContext) -> None:
    assert titles(conn, popular(ctx, "anything published before 2010", 5)) == [
        "Sharp Objects",
        "The Haunting of Hill House",
    ]


def test_work_keys_fall_back_when_no_isbn(conn: Connection, ctx: SearchContext) -> None:
    keys = work_keys(conn)

    assert all(k.startswith("t:") for k in keys.values())
    assert len(set(keys.values())) == len(keys)


def test_a_named_author_outranks_titles_that_only_resemble_a_query_word(
    conn: Connection, ctx: SearchContext
) -> None:
    # "Flynne" is one typo away from the author's surname, like "Christy" vs "Christie".
    lookalike = add_work(conn, "Flynne", first_pub_year=2001, genres=["romance"])
    add_copy(conn, add_edition(conn, lookalike, isbn13=None), "available")
    ctx = SearchContext.build(conn, today=date(2026, 10, 6))

    assert titles(conn, bm25_lookup(ctx, "anything by gillian flynn", 3))[:2] == [
        "Gone Girl",
        "Sharp Objects",
    ]


def test_extra_constraints_filter_every_query(conn: Connection, ctx: SearchContext) -> None:
    hill_house = next(w for w, t in work_titles(conn).items() if t == "The Haunting of Hill House")
    conn.execute(
        insert(schema.work_facets).values(work_id=hill_house, supernatural="yes", source="llm")
    )
    no_ghosts = replace(ctx, extra_constraints=(facet_filter(Violation.parse("supernatural=yes")),))

    assert "The Haunting of Hill House" in titles(conn, SYSTEMS["bm25"](ctx, "haunting dark", 10))
    found = titles(conn, SYSTEMS["bm25"](no_ghosts, "haunting dark", 10))
    assert "The Haunting of Hill House" not in found
    assert found  # untagged books stay


def work_titles(conn: Connection) -> dict[int, str]:
    return {r.work_id: r.title for r in conn.execute(schema.work.select())}
