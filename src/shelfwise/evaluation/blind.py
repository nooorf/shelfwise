"""A blind sample for measuring how well Claude's grades agree with a person's.

Claude grades every pooled pair; a person grades a small random sample of them without seeing
Claude's grades, and agreement on that sample is what the benchmark reports (GRADING.md). The
sample is stratified by Claude's grade, so each grade shows up often enough to measure, and spread
over queries and categories, so no single query dominates. Author and lookup queries are left
out: they are near-mechanical, and round 1 measured them already.
"""

import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shelfwise.evaluation.agreement import accuracy, cohen_kappa, within_one

SKIP_CATEGORIES = frozenset({"author", "lookup"})
GRADE_LABELS = ("0", "1", "2", "3")


@dataclass(frozen=True)
class Candidate:
    query_id: str
    work_key: str
    category: str
    suggested: int  # Claude's grade


def draw(
    candidates: Sequence[Candidate], per_grade: int, seed: int, max_per_query: int = 2
) -> list[Candidate]:
    """`per_grade` pairs for each of Claude's grades (fewer if a grade has fewer), round-robin over
    categories, at most `max_per_query` per query; returned shuffled so grades are interleaved."""
    rng = random.Random(seed)
    used: Counter[str] = Counter()
    picked: list[Candidate] = []
    for grade in (0, 1, 2, 3):
        by_category: dict[str, list[Candidate]] = defaultdict(list)
        for c in candidates:
            if c.suggested == grade and c.category not in SKIP_CATEGORIES:
                by_category[c.category].append(c)
        queues = {cat: rng.sample(pool, len(pool)) for cat, pool in sorted(by_category.items())}
        taken = 0
        while taken < per_grade and any(queues.values()):
            for queue in queues.values():
                while queue and used[queue[0].query_id] >= max_per_query:
                    queue.pop(0)
                if queue and taken < per_grade:
                    c = queue.pop(0)
                    picked.append(c)
                    used[c.query_id] += 1
                    taken += 1
    rng.shuffle(picked)
    return picked


@dataclass(frozen=True)
class Agreement:
    pairs: int
    exact: float
    within_one: float
    weighted_kappa: float | None  # quadratic weights over 0-3
    relevant_kappa: float | None  # relevant (2-3) vs not (0-1)
    confusion: dict[tuple[int, int], int]  # (person, claude) -> count
    by_category: dict[str, tuple[int, float]]  # category -> (pairs, exact)


def score(
    person: Mapping[tuple[str, str], int],
    claude: Mapping[tuple[str, str], int],
    category_of: Mapping[str, str],
) -> Agreement:
    """Agreement on the pairs both graded; pairs the person skipped don't count."""
    both = sorted(pair for pair in person if pair in claude)
    a = [str(person[p]) for p in both]
    b = [str(claude[p]) for p in both]
    relevant = ["yes" if int(x) >= 2 else "no" for x in a]
    relevant_b = ["yes" if int(x) >= 2 else "no" for x in b]
    per_category: dict[str, list[bool]] = defaultdict(list)
    for p in both:
        per_category[category_of.get(p[0], "?")].append(person[p] == claude[p])
    return Agreement(
        pairs=len(both),
        exact=accuracy(a, b),
        within_one=within_one(a, b, GRADE_LABELS),
        weighted_kappa=cohen_kappa(a, b, GRADE_LABELS, weights="quadratic"),
        relevant_kappa=cohen_kappa(relevant, relevant_b, ("no", "yes")),
        confusion=dict(Counter((person[p], claude[p]) for p in both)),
        by_category={c: (len(v), sum(v) / len(v)) for c, v in sorted(per_category.items())},
    )
