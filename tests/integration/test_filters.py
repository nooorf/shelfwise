import operator
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Connection, insert

from shelfwise.catalog import schema
from shelfwise.query.constraints import Constraint
from shelfwise.query.rules import parse_rules
from shelfwise.retrieval.filters import (
    UnsupportedConstraint,
    allowed_mask,
    allowed_work_ids,
    relaxations,
)

from .factories import add_copy, add_edition, add_work


def hard(field_name: str, op: str, value: object, **kw: object) -> Constraint:
    return Constraint(field=field_name, op=op, value=value, strength="hard", source="rule", **kw)  # type: ignore[arg-type]


def test_short_and_available_must_hold_for_the_same_edition(conn: Connection) -> None:
    work_id = add_work(conn)
    short = add_edition(conn, work_id, pages=200)
    long = add_edition(conn, work_id, pages=400)
    add_copy(conn, short, "on_loan", due_date=date(2026, 10, 20))
    add_copy(conn, long, "available")
    under_300 = hard("pages", "lt", 300)
    available = hard("available_now", "eq", True)

    assert work_id in allowed_work_ids(conn, [under_300])
    assert work_id in allowed_work_ids(conn, [available])
    assert work_id not in allowed_work_ids(conn, [under_300, available])


def test_unknown_values_fail_hard_filters(conn: Connection) -> None:
    work_id = add_work(conn)
    add_edition(conn, work_id, pages=None)

    assert work_id not in allowed_work_ids(conn, [hard("pages", "lt", 300)])
    assert work_id not in allowed_work_ids(conn, [hard("year", "gt", 2000)])


def test_year_uses_first_publication_then_earliest_edition(conn: Connection) -> None:
    classic = add_work(conn, "Classic", first_pub_year=1850)
    add_edition(conn, classic, pub_year=2015)  # a modern reprint
    undated = add_work(conn, "Undated")
    add_edition(conn, undated, pub_year=2019)
    add_edition(conn, undated, pub_year=2021)

    assert classic in allowed_work_ids(conn, [hard("year", "lt", 1900)])
    assert classic not in allowed_work_ids(conn, [hard("year", "gt", 2010)])
    assert undated in allowed_work_ids(conn, [hard("year", "eq", 2019)])


def test_excluding_a_facet_keeps_unknown_and_unclear(conn: Connection) -> None:
    ids = {}
    for value in ("yes", "no", "unclear", None):
        work_id = add_work(conn, f"Book {value}")
        if value is not None:
            conn.execute(
                insert(schema.work_facets).values(work_id=work_id, supernatural=value, source="llm")
            )
        ids[value] = work_id

    allowed = allowed_work_ids(conn, [hard("facet.supernatural", "eq", "yes", polarity="exclude")])

    assert ids["yes"] not in allowed
    assert {ids["no"], ids["unclear"], ids[None]} <= allowed


def test_genre_include_and_exclude(conn: Connection) -> None:
    horror = add_work(conn, "Scary", genres=["horror", "thriller"])
    romance = add_work(conn, "Sweet", genres=["romance"])

    assert allowed_work_ids(conn, [hard("genre", "in", ["horror"])]) >= {horror}
    assert romance not in allowed_work_ids(conn, [hard("genre", "in", ["horror"])])
    assert horror not in allowed_work_ids(conn, [hard("genre", "not_in", ["horror"])])
    assert horror not in allowed_work_ids(
        conn, [hard("genre", "in", ["horror"], polarity="exclude")]
    )


def test_soft_constraints_do_not_filter(conn: Connection) -> None:
    work_id = add_work(conn)
    add_edition(conn, work_id, pages=500)
    soft_short = Constraint(field="pages", op="lte", value=250, strength="soft", source="rule")

    assert work_id in allowed_work_ids(conn, [soft_short])


@pytest.mark.parametrize(
    "constraint",
    [
        hard("mood", "eq", "dark"),
        hard("pages", "approx", 100),
        hard("pages", "lt", "three hundred"),
        hard("available_now", "eq", False),
        hard("facet.sparkly", "eq", "yes"),
        hard("pages", "lt", 300, polarity="exclude"),
    ],
)
def test_unsupported_constraints_raise_instead_of_being_ignored(
    conn: Connection, constraint: Constraint
) -> None:
    with pytest.raises(UnsupportedConstraint):
        allowed_work_ids(conn, [constraint])


def test_mask_aligns_with_given_order(conn: Connection) -> None:
    a = add_work(conn, "A", first_pub_year=2020)
    b = add_work(conn, "B", first_pub_year=1990)

    mask = allowed_mask(conn, [hard("year", "gt", 2000)], np.array([b, a]))

    assert mask.tolist() == [False, True]


def test_relaxations_drop_a_decade_as_one_constraint(conn: Connection) -> None:
    for year, pages in [(2012, 250), (2015, 450), (1999, 200)]:
        add_edition(conn, add_work(conn, f"Thriller {year}", first_pub_year=year), pages=pages)
    constraints = parse_rules("from the 2010s under 300 pages", date(2026, 10, 6)).constraints

    found = {r.label: r.count for r in relaxations(conn, constraints)}

    assert set(found) == {"from the 2010s", "under 300 pages"}
    assert found["from the 2010s"] >= 2  # 2012 and 1999 are under 300 pages
    assert found["under 300 pages"] >= 2  # 2012 and 2015 are from the 2010s


# --- Property-based check against a plain-Python reference -----------------------------------

_OPS = {
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "eq": operator.eq,
}
STATUSES = ["available", "on_loan", "reference_only", "lost"]
GENRES = ["horror", "mystery", "romance"]


@dataclass
class FakeEdition:
    pages: int | None
    pub_year: int | None
    copies: list[str]


@dataclass
class FakeWork:
    first_pub_year: int | None
    genres: list[str]
    editions: list[FakeEdition] = field(default_factory=list)


editions = st.builds(
    FakeEdition,
    pages=st.none() | st.integers(100, 600),
    pub_year=st.none() | st.integers(1990, 2020),
    copies=st.lists(st.sampled_from(STATUSES), max_size=3),
)
works = st.builds(
    FakeWork,
    first_pub_year=st.none() | st.integers(1990, 2020),
    genres=st.lists(st.sampled_from(GENRES), unique=True, max_size=2),
    editions=st.lists(editions, min_size=1, max_size=3),
)
ops = st.sampled_from(list(_OPS))
strength = st.sampled_from(["hard", "hard", "soft"])
constraints = st.one_of(
    st.builds(lambda o, v, s: Constraint(field="pages", op=o, value=v, strength=s, source="rule"),
              ops, st.integers(100, 600), strength),
    st.builds(lambda o, v, s: Constraint(field="year", op=o, value=v, strength=s, source="rule"),
              ops, st.integers(1990, 2020), strength),
    st.builds(lambda s: Constraint(field="available_now", op="eq", value=True, strength=s, source="rule"),
              strength),
    st.builds(lambda o, v, s: Constraint(field="genre", op=o, value=v, strength=s, source="chip"),
              st.sampled_from(["in", "not_in"]), st.lists(st.sampled_from(GENRES), min_size=1, unique=True), strength),
)  # fmt: skip


def reference_allows(work: FakeWork, cs: list[Constraint]) -> bool:
    hard_cs = [c for c in cs if c.strength == "hard"]
    years = [e.pub_year for e in work.editions if e.pub_year is not None]
    year = work.first_pub_year if work.first_pub_year is not None else min(years, default=None)
    for c in hard_cs:
        if c.field == "year" and (year is None or not _OPS[c.op](year, c.value)):
            return False
        if c.field == "genre":
            overlap = bool(set(work.genres) & set(c.value))
            if overlap != (c.op == "in"):
                return False
    page_cs = [c for c in hard_cs if c.field == "pages"]
    need_available = any(c.field == "available_now" for c in hard_cs)
    if not page_cs and not need_available:
        return True
    return any(
        all(e.pages is not None and _OPS[c.op](e.pages, c.value) for c in page_cs)
        and (not need_available or "available" in e.copies)
        for e in work.editions
    )


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(catalog=st.lists(works, min_size=1, max_size=6), cs=st.lists(constraints, max_size=4))
def test_sql_filters_match_reference_semantics(
    conn: Connection, catalog: list[FakeWork], cs: list[Constraint]
) -> None:
    savepoint = conn.begin_nested()
    try:
        ids = []
        for i, w in enumerate(catalog):
            work_id = add_work(conn, f"W{i}", first_pub_year=w.first_pub_year, genres=w.genres)
            for e in w.editions:
                edition_id = add_edition(conn, work_id, pages=e.pages, pub_year=e.pub_year)
                for status in e.copies:
                    add_copy(
                        conn,
                        edition_id,
                        status,
                        due_date=date(2026, 10, 20) if status == "on_loan" else None,
                    )
            ids.append(work_id)

        allowed = allowed_work_ids(conn, cs) & set(ids)
        expected = {
            work_id for work_id, w in zip(ids, catalog, strict=True) if reference_allows(w, cs)
        }

        assert allowed == expected
    finally:
        savepoint.rollback()
