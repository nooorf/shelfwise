from datetime import date
from pathlib import Path

import pytest

from shelfwise.evaluation.conversations import (
    CATEGORIES,
    GoldTurn,
    load_conversations,
    score_turn,
    summarize,
)
from shelfwise.evaluation.parser_gold import parse_constraint
from shelfwise.query.constraints import Constraint

SET_C = Path("eval/data/conversations.yaml")


def test_the_set_loads_and_covers_every_category() -> None:
    gold = load_conversations(SET_C)

    assert gold.today == date(2026, 10, 8)
    assert len(gold.sessions) == 40
    assert {s.category for s in gold.sessions} == set(CATEGORIES)
    assert all(2 <= len(s.turns) <= 6 for s in gold.sessions)


def test_same_repeats_the_previous_state(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        "today: 2026-10-08\nsessions:\n"
        "  - id: X1\n    category: refine\n    source: llm-draft\n    turns:\n"
        "      - say: dark thrillers\n        constraints:\n          - genre in [thriller] soft\n"
        "      - say: the second one\n        constraints: same\n        targets: [2]\n"
    )

    (session,) = load_conversations(path).sessions

    assert session.turns[1].constraints == session.turns[0].constraints
    assert session.turns[1].targets == (2,)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("      - say: x\n        kind: guess\n", "kind must be one of"),
        ("      - say: x\n        action: undo\n", "exactly one of say / action"),
        ("      - say: x\n        constraints: [pages lt three hard]\n", "pages"),
        ("      - say: x\n        targets: [0]\n", "positions from 1"),
    ],
)
def test_mistakes_are_reported_with_where(tmp_path: Path, body: str, error: str) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(
        "today: 2026-10-08\nsessions:\n  - id: X1\n    category: refine\n"
        "    source: llm-draft\n    turns:\n" + body
    )

    with pytest.raises(ValueError, match=error):
        load_conversations(path)


def c(field: str, op: str, value: object, strength: str = "soft") -> Constraint:
    return Constraint(field=field, op=op, value=value, strength=strength, source="state")


def test_wildcards_match_any_value_and_the_rest_must_be_exact() -> None:
    from shelfwise.evaluation.conversations import _constraint

    gold = GoldTurn(
        say="something darker",
        kind="refine",
        constraints=(
            parse_constraint("genre in [thriller] soft"),
            _constraint("facet.darkness gte * soft"),
        ),
        drop=("darker",),
    )

    hit = score_turn("C1", 2, gold, "refine", "search",
                     [c("genre", "in", ["thriller"]), c("facet.darkness", "gte", 3)],
                     "psychological thrillers", None)  # fmt: skip
    miss = score_turn("C1", 2, gold, "new_topic", "search",
                      [c("facet.darkness", "lte", 1)], "something darker", None)  # fmt: skip

    assert hit.exact
    assert not miss.exact and miss.kind_ok is False
    assert [str(m) for m in miss.missing] == ["genre in [thriller] soft",
                                              "facet.darkness gte * soft"]  # fmt: skip
    assert miss.leaked == ["darker"]
    summary = summarize([hit, miss])
    assert (summary["turn_exact"], summary["session_success"]) == (0.5, 0.0)


def test_unscored_turns_and_targets() -> None:
    gold = GoldTurn(say="yes", constraints=None)
    ref = GoldTurn(say="the second one", targets=(2,), constraints=())

    assert score_turn(
        "C", 1, gold, "relax", "search", [c("year", "gt", 2024, "hard")], "", None
    ).exact
    assert score_turn("C", 2, ref, "reference", "explain", [], "", [2]).exact
    assert not score_turn("C", 2, ref, "reference", "explain", [], "", [3]).exact
