"""Soft constraints as a ranking signal (design doc §13.3, §15.1).

Hard constraints filter; soft ones ("cozy", "for teens", "fantasy") only move books. Each soft
constraint a book meets counts +1, each it breaks -1, and an unknown (untagged facet, missing
genre label, a shift with nothing to shift from) counts 0; the score is the mean, in [-1, 1].
A missing genre label is unknown, not a miss: the catalog's genres are too incomplete to count
against a book (PARSING.md).

Not scored yet: theme penalties (no theme data per book), `shift` (needs the previous results,
Phase 4), and soft page or year limits (the rules make those hard). Until the ranker learns
weights, `SOFT_WEIGHT` is an untuned nudge on top of RRF.
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


def _facet_match(c: Constraint, value: Any) -> int:
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


def soft_score(
    constraints: Sequence[Constraint],
    facets: Mapping[str, Any] | None,
    genres: Sequence[str],
    popularity_rank: float | None = None,
) -> float:
    """Mean of +1 (met) / -1 (broken) / 0 (unknown) over the soft constraints that apply.

    `popularity_rank` is the book's popularity percentile (1.0 = most borrowed)."""
    votes = []
    for c in constraints:
        if c.strength != "soft" or c.op == "shift":
            continue
        if c.field.startswith("facet."):
            votes.append(_facet_match(c, (facets or {}).get(c.field.removeprefix("facet."))))
        elif c.field == "genre" and c.op == "in":
            overlap = bool(set(genres) & set(c.value if isinstance(c.value, list) else [c.value]))
            if c.polarity == "exclude":
                votes.append(-1 if overlap else 0)
            else:
                votes.append(1 if overlap else 0)
        elif c.field == "popular" and popularity_rank is not None:
            votes.append(1 if popularity_rank >= 0.8 else 0)
    return sum(votes) / len(votes) if votes else 0.0
