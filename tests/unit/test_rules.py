from datetime import date
from pathlib import Path

import pytest

from shelfwise.evaluation.queries import load_queries
from shelfwise.query.constraints import Constraint, contradictions
from shelfwise.query.numbers import words_to_number
from shelfwise.query.rules import parse_rules

TODAY = date(2026, 10, 6)


def parsed(query: str) -> set[tuple[str, str, object, str]]:
    """(field, op, value, strength) for each constraint, order-free."""
    return {
        (c.field, c.op, tuple(c.value) if isinstance(c.value, list) else c.value, c.strength)
        for c in parse_rules(query, TODAY).constraints
    }


@pytest.mark.parametrize(
    ("phrase", "number"),
    [
        ("three hundred", 300),
        ("three hundred and fifty", 350),
        ("a hundred", 100),
        ("two thousand and twenty", 2020),
        ("forty-two", 42),
        ("nineteen", 19),
        ("banana", None),
        ("and", None),
    ],
)
def test_words_to_number(phrase: str, number: int | None) -> None:
    assert words_to_number(phrase) == number


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("under 300 pages", {("pages", "lt", 300, "hard")}),
        ("less than 300 pages", {("pages", "lt", 300, "hard")}),
        ("no more than 300 pages", {("pages", "lte", 300, "hard")}),
        ("300 pages or less", {("pages", "lte", 300, "hard")}),
        ("over 500 pages", {("pages", "gt", 500, "hard")}),
        ("at least 400 pages", {("pages", "gte", 400, "hard")}),
        (
            "between 200 and 350 pages",
            {("pages", "gte", 200, "hard"), ("pages", "lte", 350, "hard")},
        ),
        ("under three hundred pages", {("pages", "lt", 300, "hard")}),  # voice transcript
        ("a 100 page novel", {("pages", "approx", 100, "soft")}),
        ("around 300 pages", {("pages", "approx", 300, "soft")}),
        ("ideally under 300 pages", {("pages", "lt", 300, "soft")}),
        ("under 300 pages if possible", {("pages", "lt", 300, "soft")}),
        (
            "a mystery about murder under 300 pages",
            {("pages", "lt", 300, "hard")},
        ),  # "about" isn't a hedge
        ("something short", {("pages", "lte", 250, "soft")}),
        ("not too long please", {("pages", "lte", 250, "soft")}),
        ("something i can finish in a weekend", {("pages", "lte", 250, "soft")}),
        ("a long epic fantasy", {("pages", "gte", 450, "soft")}),
        ("short stories", set()),  # a genre, not a length
        ("a short horror book under 250 pages", {("pages", "lt", 250, "hard")}),  # hard wins
    ],
)
def test_pages(query: str, expected: set[tuple[str, str, object, str]]) -> None:
    assert parsed(query) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("published after 2015", {("year", "gt", 2015, "hard")}),
        ("since 2015", {("year", "gte", 2015, "hard")}),
        ("from 2015 onwards", {("year", "gte", 2015, "hard")}),
        ("before 1900", {("year", "lt", 1900, "hard")}),
        ("written in 2025", {("year", "eq", 2025, "hard")}),
        ("a thriller from 2019", {("year", "eq", 2019, "hard")}),
        ("between 2000 and 2010", {("year", "gte", 2000, "hard"), ("year", "lte", 2010, "hard")}),
        ("from the 2010s", {("year", "gte", 2010, "hard"), ("year", "lte", 2019, "hard")}),
        ("horror from the 90s", {("year", "gte", 1990, "hard"), ("year", "lte", 1999, "hard")}),
        ("published in the last 10 years", {("year", "gte", 2016, "hard")}),
        ("from the past few years", {("year", "gte", 2021, "hard")}),
        ("something recent", {("year", "gte", 2021, "soft")}),
        ("a novel set in the 1920s", set()),  # setting, not publication
        ("set in 1920", set()),
        ("books like 1984", set()),  # a title, not a year
        ("is nineteen eighty four in", set()),
    ],
)
def test_years(query: str, expected: set[tuple[str, str, object, str]]) -> None:
    assert parsed(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "thrillers i can take home today",
        "what horror books are available right now",
        "available young adult fantasy on the shelf",
        "anything not checked out",
        "something i could borrow today",
    ],
)
def test_availability_phrases(query: str) -> None:
    assert parsed(query) == {("available_now", "eq", True, "hard")}


@pytest.mark.parametrize(
    "query",
    [
        "i don't care if it's available",
        "even if it's not available right now",
        "is the shining checked out",
    ],
)
def test_no_availability_filter(query: str) -> None:
    assert parsed(query) == set()


def test_isbn_in_text() -> None:
    assert parsed("do you have 978-1-250-30169-7") == {("isbn", "in", ("9781250301697",), "hard")}


@pytest.mark.parametrize(
    ("query", "residual"),
    [
        ("mystery under 300 pages published after 2015", "mystery"),
        ("thriller from the 2010s, not too long", "thriller"),
        ("thrillers i can take home today", "thrillers"),
        ("short classic novel i can finish in a weekend", "classic novel"),
        (
            "an available 100 page japanese cyberpunk novel written in 2025",
            "japanese cyberpunk novel",
        ),
        (
            "something dark and psychological with a twist",
            "something dark and psychological with a twist",
        ),
    ],
)
def test_residual_keeps_only_the_meaning(query: str, residual: str) -> None:
    assert parse_rules(query, TODAY).residual == residual


def test_spans_record_the_source_words() -> None:
    constraints = parse_rules("Mystery under 300 pages, published after 2015", TODAY).constraints

    assert {c.span for c in constraints} == {"under 300 pages", "published after 2015"}
    assert all(c.source == "rule" for c in constraints)


def test_contradiction_detected() -> None:
    constraints = parse_rules("books over 500 pages but under 300 pages", TODAY).constraints

    (found,) = contradictions(constraints)
    assert found.field == "pages"
    assert "can't both hold" in found.message()


def test_soft_constraints_never_contradict() -> None:
    soft = Constraint(field="pages", op="lte", value=250, strength="soft", source="rule")
    hard = Constraint(field="pages", op="gt", value=500, strength="hard", source="rule")

    assert contradictions([soft, hard]) == []


def test_every_eval_query_parses_without_error() -> None:
    queries = load_queries(Path(__file__).resolve().parents[2] / "eval" / "data" / "queries.csv")

    for q in queries:
        result = parse_rules(q.text, TODAY)
        assert isinstance(result.residual, str)
