import pytest

from shelfwise.query.constraints import Constraint
from shelfwise.ranking.soft import soft_score


def soft(field: str, op: str, value: object, exclude: bool = False) -> Constraint:
    return Constraint.model_validate(
        {
            "field": field,
            "op": op,
            "value": value,
            "strength": "soft",
            "source": "llm",
            "polarity": "exclude" if exclude else "include",
        }
    )


COZY = soft("facet.darkness", "lte", 1)
TEENS = soft("facet.audience", "eq", "ya")
FANTASY = soft("genre", "in", ["fantasy"])


@pytest.mark.parametrize(
    ("facets", "genres", "expected"),
    [
        ({"darkness": 0, "audience": "ya"}, ["fantasy"], 1.0),  # meets all three
        ({"darkness": 3, "audience": "adult"}, ["fantasy"], -1 / 3),  # breaks two
        ({"darkness": 1, "audience": None}, [], 1 / 3),  # untagged and unlabelled count 0
        (None, [], 0.0),  # never tagged
    ],
)
def test_mean_of_met_broken_and_unknown(facets: dict | None, genres: list, expected: float) -> None:
    assert soft_score([COZY, TEENS, FANTASY], facets, genres) == pytest.approx(expected)


def test_hard_constraints_and_shifts_are_not_scored() -> None:
    hard = COZY.model_copy(update={"strength": "hard"})
    shift = soft("facet.darkness", "shift", -1)

    assert soft_score([hard, shift], {"darkness": 3}, []) == 0.0


def test_unclear_and_exclusions() -> None:
    magic = soft("facet.supernatural", "eq", "yes")
    no_magic = soft("facet.supernatural", "eq", "yes", exclude=True)

    assert soft_score([magic], {"supernatural": "unclear"}, []) == 0.0
    assert soft_score([no_magic], {"supernatural": "yes"}, []) == -1.0
    assert soft_score([no_magic], {"supernatural": "no"}, []) == 1.0


def test_popular_needs_the_top_fifth() -> None:
    popular = soft("popular", "eq", True)

    assert soft_score([popular], None, [], popularity_rank=0.9) == 1.0
    assert soft_score([popular], None, [], popularity_rank=0.5) == 0.0
