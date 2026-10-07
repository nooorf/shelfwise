from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from shelfwise.evaluation.parser_gold import GoldConstraint, load_gold, parse_constraint
from shelfwise.evaluation.queries import load_queries
from shelfwise.query.request import constraint_problems, parse_rules_only

DATA = Path(__file__).resolve().parents[2] / "eval" / "data"
GOLD = DATA / "parser_gold.yaml"
QUERIES = DATA / "queries.csv"


def test_committed_gold_is_valid_and_covers_set_a() -> None:
    gold = load_gold(GOLD, QUERIES)
    ids = {g.id for g in gold.queries}
    extra = [g for g in gold.queries if not g.in_set_a]

    assert {q.id for q in load_queries(QUERIES)} <= ids
    assert len(extra) >= 100
    assert Counter(g.category for g in extra).keys() >= {"refinement", "followup", "other"}


def test_rule_parser_output_stays_inside_the_vocabulary() -> None:
    gold = load_gold(GOLD, QUERIES)
    for g in gold.queries:
        for c in parse_rules_only(g.text, gold.today).constraints:
            assert constraint_problems(c.field, c.op, c.value) == [], g.id


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("pages lt 300 hard", GoldConstraint("pages", "lt", 300, "hard")),
        ("genre in [mystery, thriller] soft", GoldConstraint("genre", "in", ["mystery", "thriller"], "soft")),
        ("not facet.supernatural eq yes hard", GoldConstraint("facet.supernatural", "eq", "yes", "hard", "exclude")),
        ("not theme eq animal deaths soft", GoldConstraint("theme", "eq", "animal deaths", "soft", "exclude")),
        ("facet.fiction eq false soft", GoldConstraint("facet.fiction", "eq", False, "soft")),
        ("facet.darkness shift -1 soft", GoldConstraint("facet.darkness", "shift", -1, "soft")),
        ("isbn in [9780061120084] hard", GoldConstraint("isbn", "in", ["9780061120084"], "hard")),
    ],
)  # fmt: skip
def test_parse_constraint(spec: str, expected: GoldConstraint) -> None:
    parsed = parse_constraint(spec)
    assert parsed == expected
    assert parse_constraint(str(parsed)) == parsed  # prints back in the same syntax


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("pages lt 300", "expected"),
        ("pages below 300 hard", "unknown op"),
        ("pages lt 300 firm", "strength"),
        ("pagecount lt 300 hard", "unknown field"),
        ("genre in [spy novels] soft", "bad value"),
        ("facet.darkness gte 5 soft", "bad value"),
        ("facet.supernatural lte yes hard", "not allowed"),
        ("pages shift 2 soft", "shift takes"),
    ],
)
def test_parse_constraint_rejects(spec: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_constraint(spec)


def test_loader_reports_every_problem_by_id(tmp_path: Path) -> None:
    path = tmp_path / "gold.yaml"
    path.write_text(
        """
today: 2026-10-07
queries:
  - id: L01
    intent: lookup
    text: do you have the silent patient
  - id: B1
    intent: discover
  - id: B2
    text: something
    category: genre
    source: llm-draft
    intent: browse
  - id: B3
    text: something
    category: genre
    source: llm-draft
    intent: discover
    constraints: [pages under 300 hard]
  - id: B3
    text: other
    category: genre
    source: llm-draft
    intent: discover
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error:
        load_gold(path, QUERIES)

    message = str(error.value)
    assert "L01: ['text'] come from queries.csv" in message
    assert "B1: not in set A, so it needs ['category', 'source', 'text']" in message
    assert "B2: intent must be one of" in message
    assert "B3: 'pages under 300 hard': unknown op" in message
    assert "B3: duplicate id" in message


def test_loader_needs_a_reference_date(tmp_path: Path) -> None:
    path = tmp_path / "gold.yaml"
    path.write_text("queries: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="today"):
        load_gold(path, QUERIES)


def test_set_a_rows_show_their_query_text() -> None:
    """Each set A row has its query as a comment above it, so a reviewer reads them together.
    If a query's text changes in queries.csv, update the comment and re-check its gold parse."""
    texts = {q.id: q.text for q in load_queries(QUERIES)}
    lines = GOLD.read_text(encoding="utf-8").splitlines()
    shown = {}
    for above, line in pairwise(lines):
        if line.startswith("  - id: ") and (query_id := line.removeprefix("  - id: ")) in texts:
            shown[query_id] = above.removeprefix("  # ") if above.startswith("  # ") else None

    assert shown == texts
