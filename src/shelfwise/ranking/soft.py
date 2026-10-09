"""Soft constraints as a ranking signal (design doc §13.3, §15.1).

Hard constraints filter; soft ones ("cozy", "for teens", "fantasy") only move books. Each soft
constraint a book meets counts +1, each it breaks -1, and an unknown (untagged facet, missing
genre label, a shift with nothing to shift from) counts 0; the score is the mean, in [-1, 1].
A missing genre label is unknown, not a miss: the catalog's genres are too incomplete to count
against a book (PARSING.md).

Page and year preferences count too: the conversation turns "shorter" into a soft page limit
from the books just shown. Not scored: theme penalties (no theme data per book) and unresolved
`shift`s. Until the ranker learns weights, `SOFT_WEIGHT` is an untuned nudge on top of RRF.
"""

import operator
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from shelfwise.query.constraints import Constraint

# RRF's top score with two lists is 2/61 ~ 0.033 and rank 20's is 2/80 = 0.025, so a book that
# meets every soft constraint moves up roughly 15-25 places; untuned until the fusion grid.
SOFT_WEIGHT = 0.01

_COMPARE: dict[str, Callable[[Any, Any], bool]] = {
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "eq": operator.eq,
}
_BOOL_FACETS = {"fiction"}  # stored as a boolean; the parser says True / False
_YES_NO_FACETS = {"supernatural", "historical_setting"}  # 'yes' / 'no' / 'unclear'


def facet_match(c: Constraint, value: Any) -> int:
    if value is None or c.op not in _COMPARE:
        return 0
    name = c.field.removeprefix("facet.")
    if name in _YES_NO_FACETS and value == "unclear":
        return 0
    try:
        met = _COMPARE[c.op](value, c.value)
    except TypeError:  # e.g. a string scale compared with a number
        return 0
    if c.polarity == "exclude":
        met = not met
    return 1 if met else -1


def _number_match(c: Constraint, value: int | None) -> int:
    if value is None or c.op not in _COMPARE or not isinstance(c.value, int | float):
        return 0
    met = _COMPARE[c.op](value, c.value)
    if c.polarity == "exclude":
        met = not met
    return 1 if met else -1


def scored(c: Constraint) -> bool:
    """Whether `soft_score` counts `c` as a preference (a chip can switch to "preferred")."""
    if c.op == "shift":
        return False
    if c.field.startswith("facet."):
        return c.op in _COMPARE
    if c.field == "genre":
        return c.op == "in"
    if c.field in ("pages", "year"):
        number = isinstance(c.value, int | float) and not isinstance(c.value, bool)
        return c.op in _COMPARE and number
    return c.field == "popular"


def soft_score(
    constraints: Sequence[Constraint],
    facets: Mapping[str, Any] | None,
    genres: Sequence[str],
    popularity_rank: float | None = None,
    pages: int | None = None,
    year: int | None = None,
) -> float:
    """Mean of +1 (met) / -1 (broken) / 0 (unknown) over the soft constraints that apply.

    `popularity_rank` is the book's popularity percentile (1.0 = most borrowed)."""
    votes = []
    for c in constraints:
        if c.strength != "soft" or c.op == "shift":
            continue
        if c.field.startswith("facet."):
            votes.append(facet_match(c, (facets or {}).get(c.field.removeprefix("facet."))))
        elif c.field == "genre" and c.op == "in":
            overlap = bool(set(genres) & set(c.value if isinstance(c.value, list) else [c.value]))
            if c.polarity == "exclude":
                votes.append(-1 if overlap else 0)
            else:
                votes.append(1 if overlap else 0)
        elif c.field == "pages":
            votes.append(_number_match(c, pages))
        elif c.field == "year":
            votes.append(_number_match(c, year))
        elif c.field == "popular" and popularity_rank is not None:
            votes.append(1 if popularity_rank >= 0.8 else 0)
    return sum(votes) / len(votes) if votes else 0.0
