"""Score a parser against gold set B (design doc §28).

- **Constraints:** per-field precision, recall and F1. A predicted constraint counts only if field,
  op, value, strength and polarity all match a gold one ("strict"); "lenient" ignores strength,
  to separate "found the right filter" from "got hard vs soft right".
- **Exact match:** intent, lookup, seeds and the whole constraint set all correct (strict).
  `semantic_query` is free text, so it's scored separately and not part of exact match:
- **Keep recall:** share of gold keep phrases that survive into `semantic_query`.
- **Negation leak rate:** share of queries with negated words where one still appears in
  `semantic_query`. A leaked "supernatural" pulls supernatural books *closer* in embedding space.

Values compare after folding case and punctuation. Titles compare fuzzily (typos are the entity
linker's problem, not the scorer's); themes match when one phrase contains the other.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from shelfwise.evaluation.parser_gold import GoldConstraint, GoldParse
from shelfwise.ingest.normalize import fold_text, title_norm
from shelfwise.query.request import ParsedRequest

TITLE_SIMILARITY = 90
THEME_SIMILARITY = 85


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass
class QueryResult:
    id: str
    category: str
    gold_intent: str
    intent: str
    lookup_ok: bool
    seeds_ok: bool
    missing: list[GoldConstraint]  # in gold, not predicted (strict)
    extra: list[GoldConstraint]  # predicted, not in gold (strict)
    matched: list[GoldConstraint]
    lenient: Counts
    keep_found: int
    keep_total: int
    leaked: list[str]
    has_drop: bool
    has_lookup: bool  # gold or prediction has a lookup / seeds: the denominators for accuracy
    has_seeds: bool

    @property
    def intent_ok(self) -> bool:
        return self.intent == self.gold_intent

    @property
    def exact(self) -> bool:
        return (
            self.intent_ok
            and self.lookup_ok
            and self.seeds_ok
            and not self.missing
            and not self.extra
        )


def _alternatives(text: str) -> list[str]:
    return [alt.strip() for alt in text.split(" | ") if alt.strip()]


def _title_match(gold: str, predicted: str) -> bool:
    return any(
        fuzz.ratio(title_norm(alt), title_norm(predicted)) >= TITLE_SIMILARITY
        for alt in _alternatives(gold)
    )


def _name_match(gold: str, predicted: str) -> bool:
    return any(
        fuzz.ratio(fold_text(alt), fold_text(predicted)) >= TITLE_SIMILARITY
        for alt in _alternatives(gold)
    )


def _theme_match(gold: str, predicted: str) -> bool:
    p = fold_text(predicted)
    for alt in map(fold_text, _alternatives(gold)):
        if f" {alt} " in f" {p} " or f" {p} " in f" {alt} ":
            return True
        if fuzz.token_set_ratio(alt, p) >= THEME_SIMILARITY:
            return True
    return False


def _folded(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(sorted(str(_folded(v)) for v in value))
    return fold_text(value) if isinstance(value, str) else value


def _same_value(name: str, gold: Any, predicted: Any) -> bool:
    if name == "title" and isinstance(gold, str) and isinstance(predicted, str):
        return _title_match(gold, predicted)
    if name == "theme" and isinstance(gold, str) and isinstance(predicted, str):
        return _theme_match(gold, predicted)
    if isinstance(gold, bool) != isinstance(predicted, bool):  # True == 1 in Python
        return False
    return _folded(gold) == _folded(predicted)


def _same(gold: GoldConstraint, predicted: GoldConstraint, strict: bool) -> bool:
    return (
        gold.field == predicted.field
        and gold.op == predicted.op
        and gold.polarity == predicted.polarity
        and (gold.strength == predicted.strength or not strict)
        and _same_value(gold.field, gold.value, predicted.value)
    )


def match_constraints(
    gold: Sequence[GoldConstraint], predicted: Sequence[GoldConstraint], strict: bool = True
) -> tuple[list[GoldConstraint], list[GoldConstraint], list[GoldConstraint]]:
    """Greedy one-to-one matching: (matched gold, missing gold, extra predicted)."""
    unused = list(predicted)
    matched, missing = [], []
    for g in gold:
        hit = next((p for p in unused if _same(g, p, strict)), None)
        if hit is None:
            missing.append(g)
        else:
            matched.append(g)
            unused.remove(hit)
    return matched, missing, unused


def _plural_pattern(phrase: str) -> str:
    if phrase.endswith("y"):  # mystery -> mysteries
        return rf"\b{re.escape(phrase[:-1])}(?:y|ies)\b"
    return rf"\b{re.escape(phrase)}(?:s|es)?\b"


def mentions(text: str, phrase: str) -> bool:
    """Whole-word match on folded text, plurals allowed; any " | " alternative counts."""
    folded = fold_text(text)
    return any(
        re.search(_plural_pattern(fold_text(alt)), folded)
        for alt in _alternatives(phrase)
        if fold_text(alt)
    )


def _lookup_ok(gold: GoldParse, predicted: ParsedRequest) -> bool:
    spec = predicted.lookup
    title, author = (spec.title, spec.author) if spec else (None, None)
    if (gold.title is None) != (title is None) or (gold.author is None) != (author is None):
        return False
    return (gold.title is None or _title_match(gold.title, title or "")) and (
        gold.author is None or _name_match(gold.author, author or "")
    )


def _seeds_ok(gold: GoldParse, predicted: ParsedRequest) -> bool:
    unused = list(predicted.seed_titles)
    for seed in gold.seeds:
        hit = next((p for p in unused if _title_match(seed, p)), None)
        if hit is None:
            return False
        unused.remove(hit)
    return not unused


def as_gold(predicted: ParsedRequest) -> list[GoldConstraint]:
    return [
        GoldConstraint(c.field, c.op, c.value, c.strength, c.polarity)
        for c in predicted.constraints
    ]


def score_query(gold: GoldParse, predicted: ParsedRequest) -> QueryResult:
    produced = as_gold(predicted)
    matched, missing, extra = match_constraints(gold.constraints, produced)
    loose, loose_missing, loose_extra = match_constraints(gold.constraints, produced, strict=False)
    has_lookup = gold.title is not None or gold.author is not None or predicted.lookup is not None
    return QueryResult(
        id=gold.id,
        category=gold.category,
        gold_intent=gold.intent,
        intent=predicted.intent,
        lookup_ok=_lookup_ok(gold, predicted),
        seeds_ok=_seeds_ok(gold, predicted),
        missing=missing,
        extra=extra,
        matched=matched,
        lenient=Counts(len(loose), len(loose_extra), len(loose_missing)),
        keep_found=sum(mentions(predicted.semantic_query, k) for k in gold.keep),
        keep_total=len(gold.keep),
        leaked=[d for d in gold.drop if mentions(predicted.semantic_query, d)],
        has_drop=bool(gold.drop),
        has_lookup=has_lookup,
        has_seeds=bool(gold.seeds or predicted.seed_titles),
    )


def _share(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


@dataclass
class Summary:
    n: int
    intent_accuracy: float | None
    exact_match: float | None
    lookup_accuracy: float | None
    seed_accuracy: float | None
    strict: Counts
    lenient: Counts
    per_field: dict[str, Counts]
    keep_recall: float | None
    leak_rate: float | None
    intent_confusions: dict[str, int] = field(default_factory=dict)  # "gold -> predicted"
    per_category: dict[str, dict[str, float | int | None]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "intent_accuracy": self.intent_accuracy,
            "exact_match": self.exact_match,
            "lookup_accuracy": self.lookup_accuracy,
            "seed_accuracy": self.seed_accuracy,
            "constraints_strict": self.strict.as_dict(),
            "constraints_lenient": self.lenient.as_dict(),
            "per_field": {name: c.as_dict() for name, c in sorted(self.per_field.items())},
            "keep_recall": self.keep_recall,
            "negation_leak_rate": self.leak_rate,
            "intent_confusions": self.intent_confusions,
            "per_category": self.per_category,
        }


def summarize(results: Sequence[QueryResult]) -> Summary:
    strict, lenient = Counts(), Counts()
    per_field: dict[str, Counts] = {}
    for r in results:
        for found, attr in ((r.matched, "tp"), (r.missing, "fn"), (r.extra, "fp")):
            for c in found:
                counts = per_field.setdefault(c.field, Counts())
                setattr(counts, attr, getattr(counts, attr) + 1)
                setattr(strict, attr, getattr(strict, attr) + 1)
        lenient.tp += r.lenient.tp
        lenient.fp += r.lenient.fp
        lenient.fn += r.lenient.fn

    lookups = [r for r in results if r.has_lookup]
    seeded = [r for r in results if r.has_seeds]
    dropping = [r for r in results if r.has_drop]
    confusions = Counter(f"{r.gold_intent} -> {r.intent}" for r in results if not r.intent_ok)
    per_category: dict[str, dict[str, float | int | None]] = {}
    for category in sorted({r.category for r in results}):
        rows = [r for r in results if r.category == category]
        per_category[category] = {
            "n": len(rows),
            "exact_match": _share(sum(r.exact for r in rows), len(rows)),
            "intent_accuracy": _share(sum(r.intent_ok for r in rows), len(rows)),
        }
    return Summary(
        n=len(results),
        intent_accuracy=_share(sum(r.intent_ok for r in results), len(results)),
        exact_match=_share(sum(r.exact for r in results), len(results)),
        lookup_accuracy=_share(sum(r.lookup_ok for r in lookups), len(lookups)),
        seed_accuracy=_share(sum(r.seeds_ok for r in seeded), len(seeded)),
        strict=strict,
        lenient=lenient,
        per_field=per_field,
        keep_recall=_share(sum(r.keep_found for r in results), sum(r.keep_total for r in results)),
        leak_rate=_share(sum(bool(r.leaked) for r in dropping), len(dropping)),
        intent_confusions=dict(confusions.most_common()),
        per_category=per_category,
    )
