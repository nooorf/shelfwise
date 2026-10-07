from collections.abc import Sequence

import pytest

from shelfwise.evaluation.negation import NegationPair, Violation
from shelfwise.evaluation.negation_study import (
    Condition,
    facet_filter,
    run_study,
    soft_penalty,
    violation_rate,
)
from shelfwise.evaluation.queries import Query
from shelfwise.query.constraints import Constraint


def test_facet_filter_is_a_null_safe_exclusion() -> None:
    romance = facet_filter(Violation.parse("romance>=2"))
    supernatural = facet_filter(Violation.parse("supernatural=yes"))

    assert (romance.field, romance.op, romance.value, romance.polarity) == (
        "facet.romance", "gte", 2, "exclude",
    )  # fmt: skip
    assert (supernatural.op, supernatural.value, supernatural.strength) == ("eq", "yes", "hard")


def test_soft_penalty_moves_flagged_books_down() -> None:
    ranked = list(range(1, 13))

    assert soft_penalty(ranked, {1}, penalty=3) == [2, 3, 4, 1, 5, 6, 7, 8, 9, 10, 11, 12]
    assert soft_penalty(ranked, {11, 12}, penalty=10)[-2:] == [11, 12]  # past the end: last
    assert soft_penalty(ranked, set()) == ranked


def test_violation_rate_ignores_unlabelled_books() -> None:
    tags = {"a": {"romance": "3"}, "b": {"romance": "0"}, "c": {"romance": None}}
    rate, labelled = violation_rate(["a", "b", "c", "d"], tags, Violation.parse("romance>=2"), 10)

    assert (rate, labelled) == (0.5, 2)
    assert violation_rate(["d"], tags, Violation.parse("romance>=2"), 10) == (None, 0)


PAIR = NegationPair("X1", "supernatural", Violation.parse("supernatural=yes"), "X1B", "X1N")
QUERIES = {
    "X1B": Query("X1B", "discovery", "casual", "X1", "llm-draft", "a creepy gothic novel"),
    "X1N": Query(
        "X1N",
        "negation",
        "casual",
        "X1",
        "llm-draft",
        "a creepy gothic novel, nothing supernatural",
    ),
}
KEY_OF = {1: "ghost", 2: "human", 3: "witch", 4: "asylum"}
TAGS = {"ghost": {"supernatural": "yes"}, "human": {"supernatural": "no"},
        "witch": {"supernatural": "yes"}, "asylum": {"supernatural": "no"}}  # fmt: skip
QRELS = {"X1N": {"human": 3, "asylum": 2, "ghost": 0, "witch": 1}, "X1B": {"ghost": 3}}


def fake_rank(system: str, text: str, extra: Sequence[Constraint], k: int) -> list[int]:
    """Embeddings 'love' the negated word: the raw negated query ranks ghost stories first."""
    ranked = [1, 3, 2, 4] if "supernatural" in text else [2, 1, 4, 3]
    if extra:  # the hard facet filter: the LLM tagged books 1 and 2 as supernatural
        ranked = [w for w in ranked if w not in {1, 2}]
    return ranked[:k]


def study(tagged: set[int]):  # type: ignore[no-untyped-def]
    conditions = [
        Condition("dense", t, f) for t in ("raw", "stripped") for f in ("off", "soft", "hard")
    ]  # type: ignore[arg-type]
    return run_study(
        [PAIR], QUERIES, conditions, fake_rank, KEY_OF, {"X1": tagged}, TAGS, QRELS, k=2
    )


def test_grid_by_hand() -> None:
    result = study(tagged={1, 2})  # the tagger wrongly flags book 2 ("human")
    v10 = {str(c): cell.violation_at_10["X1"] for c, cell in result.cells.items()}

    assert v10["dense/raw/off"] == 1.0  # ghost, witch
    assert v10["dense/stripped/off"] == 0.5  # human, ghost
    assert v10["dense/raw/hard"] == 0.5  # witch (untagged by the LLM), asylum
    assert v10["dense/raw/soft"] == 0.5  # ghost and human sink below the untagged: witch, asylum
    assert result.cells[Condition("dense", "raw", "off")].ranked["X1"] == ["ghost", "witch"]
    assert result.base_rate["dense"].violation_at_10["X1"] == 0.5
    assert result.recall_cost["X1"] == {"relevant": 2, "removed": 1, "wrongly_removed": 1}


def test_ndcg_uses_the_negated_querys_grades() -> None:
    result = study(tagged={1})
    off = result.cells[Condition("dense", "stripped", "off")]

    # human (3), ghost (0) against ideal human (3), asylum (2)
    assert off.ndcg_at_10["X1"] == pytest.approx(7 / (7 + 3 / 1.584962500721156))
    summary = off.summary()
    assert summary["labelled@10"] == 2.0
