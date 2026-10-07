"""The negation study's grid and metrics (design doc §40.1 B).

For every pair and every condition — retrieval system x query text x facet handling — rank books
for the negated request and measure:

- **violation rate @5 / @10:** share of the top books that have what the person ruled out,
  judged from *human* tags. Books nobody has labelled are left out of the rate, and
  `labelled@10` reports how many that was.
- **NDCG@10** against the negated query's relevance grades.

Query text: `raw` is the negated query as typed; `stripped` is the pair's base query, which is
the same request with the negation removed: perfect stripping, an upper bound for the parser.

Facet handling uses the LLM's tags (what production has): `off`; `soft` moves each book the
tags say violates down `SOFT_PENALTY` places; `hard` filters them out (NULL-safe: untagged books
stay). Two references: the **base rate** (violation rate @10 of the base query, raw, facets off:
how common the attribute is anyway) and the hard filter's **recall cost** (relevant books the
filter removes, split into real violations and tagger mistakes).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from shelfwise.evaluation.metrics import RELEVANT_GRADE, bootstrap_ci, mean, ndcg_at_k
from shelfwise.evaluation.negation import NegationPair, Violation
from shelfwise.evaluation.queries import Query
from shelfwise.query.constraints import Constraint

QueryText = Literal["raw", "stripped"]
FacetMode = Literal["off", "soft", "hard"]
SOFT_PENALTY = 10  # places a tagged violator moves down; ~one page of results
SOFT_DEPTH = 50  # results fetched before the soft penalty reorders them
K = 10

# (system, query text, extra hard constraints, k) -> ranked work ids
Ranker = Callable[[str, str, Sequence[Constraint], int], list[int]]
HumanTags = Mapping[str, Mapping[str, str | None]]  # work_key -> tag -> value


@dataclass(frozen=True)
class Condition:
    system: str
    text: QueryText
    facets: FacetMode

    def __str__(self) -> str:
        return f"{self.system}/{self.text}/{self.facets}"


def facet_filter(violation: Violation) -> Constraint:
    """The hard filter that removes books the tags say violate: 'romance>=2' -> exclude
    romance >= 2. Written as an exclusion so untagged books are kept, not dropped."""
    value: str | int = int(violation.value) if violation.op == ">=" else violation.value
    return Constraint(
        field=f"facet.{violation.facet}",
        op="gte" if violation.op == ">=" else "eq",
        value=value,
        strength="hard",
        source="llm",
        polarity="exclude",
    )


def soft_penalty(
    ranked: Sequence[int], flagged: set[int], penalty: int = SOFT_PENALTY
) -> list[int]:
    """Move each flagged book down `penalty` places; unflagged books keep their order."""
    keyed = [(i + (penalty + 0.5 if w in flagged else 0), w) for i, w in enumerate(ranked)]
    return [w for _, w in sorted(keyed, key=lambda pair: pair[0])]


def violation_rate(
    keys: Sequence[str], tags: HumanTags, violation: Violation, k: int
) -> tuple[float | None, int]:
    """(share of labelled top-k books that violate, how many of the top k were labelled)."""
    verdicts = [violation.check(tags.get(key, {})) for key in keys[:k]]
    known = [v for v in verdicts if v is not None]
    return (sum(known) / len(known) if known else None), len(known)


@dataclass
class Cell:
    """One condition's per-pair values (None where a pair has nothing to measure)."""

    violation_at_5: dict[str, float] = field(default_factory=dict)
    violation_at_10: dict[str, float] = field(default_factory=dict)
    labelled_at_10: dict[str, int] = field(default_factory=dict)
    ndcg_at_10: dict[str, float] = field(default_factory=dict)
    ranked: dict[str, list[str]] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        def stat(values: dict[str, float]) -> dict[str, object]:
            v = list(values.values())
            return {
                "mean": mean(v) if v else None,
                "ci95": bootstrap_ci(v) if v else None,
                "n": len(v),
            }

        return {
            "violation@5": stat(self.violation_at_5),
            "violation@10": stat(self.violation_at_10),
            "labelled@10": mean([float(n) for n in self.labelled_at_10.values()]),
            "ndcg@10": stat(self.ndcg_at_10),
        }


@dataclass
class StudyResult:
    cells: dict[Condition, Cell]
    base_rate: dict[str, Cell]  # per system: the base query, raw, facets off
    recall_cost: dict[str, dict[str, int]]  # per pair: relevant / removed / wrongly removed


def run_study(
    pairs: Sequence[NegationPair],
    queries: Mapping[str, Query],
    conditions: Sequence[Condition],
    rank: Ranker,
    key_of: Mapping[int, str],
    tagged_violators: Mapping[str, set[int]],  # per pair: work ids the LLM tags say violate
    tags: HumanTags,
    qrels: Mapping[str, Mapping[str, int]],
    k: int = K,
) -> StudyResult:
    def measure(cell: Cell, pair: NegationPair, ids: list[int], graded_by: str) -> None:
        keys = [key_of[w] for w in ids[:k]]
        cell.ranked[pair.pair] = keys
        at5, _ = violation_rate(keys, tags, pair.violation, 5)
        at10, labelled = violation_rate(keys, tags, pair.violation, k)
        if at5 is not None:
            cell.violation_at_5[pair.pair] = at5
        if at10 is not None:
            cell.violation_at_10[pair.pair] = at10
        cell.labelled_at_10[pair.pair] = labelled
        grades = qrels.get(graded_by, {})
        if any(g >= RELEVANT_GRADE for g in grades.values()):
            cell.ndcg_at_10[pair.pair] = ndcg_at_k(keys, grades, k)

    cells: dict[Condition, Cell] = {}
    for condition in conditions:
        cell = cells[condition] = Cell()
        for pair in pairs:
            text = queries[pair.negated if condition.text == "raw" else pair.base].text
            extra = [facet_filter(pair.violation)] if condition.facets == "hard" else []
            depth = SOFT_DEPTH if condition.facets == "soft" else k
            ids = rank(condition.system, text, extra, depth)
            if condition.facets == "soft":
                ids = soft_penalty(ids, tagged_violators.get(pair.pair, set()))
            measure(cell, pair, ids, pair.negated)

    base_rate: dict[str, Cell] = {}
    for system in dict.fromkeys(c.system for c in conditions):
        cell = base_rate[system] = Cell()
        for pair in pairs:
            measure(cell, pair, rank(system, queries[pair.base].text, [], k), pair.base)

    recall_cost: dict[str, dict[str, int]] = {}
    work_of = {key: w for w, key in key_of.items()}
    for pair in pairs:
        relevant = [key for key, g in qrels.get(pair.negated, {}).items() if g >= RELEVANT_GRADE]
        removed = [
            key for key in relevant if work_of.get(key) in tagged_violators.get(pair.pair, set())
        ]
        wrongly = [key for key in removed if pair.violation.check(tags.get(key, {})) is False]
        recall_cost[pair.pair] = {
            "relevant": len(relevant),
            "removed": len(removed),
            "wrongly_removed": len(wrongly),
        }
    return StudyResult(cells, base_rate, recall_cost)
