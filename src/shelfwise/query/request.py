"""What query understanding produces for one message (design doc §12.1).

The rule parser, the LLM parser and the parser gold set (eval set B) all speak this contract.
`FIELDS` is the controlled vocabulary: which constraint fields exist, which operators each allows
and what values are valid. The LLM's output is checked against it, and so is the gold set.

Named `ParsedRequest` rather than the design doc's `SearchRequest`, which is the API's request body.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from shelfwise.ingest.genres import GENRES
from shelfwise.query.constraints import Constraint, Op
from shelfwise.query.rules import RuleParse, parse_rules

Intent = Literal[
    "lookup", "discover", "similar", "refine", "compare", "explain", "surprise", "other"
]
INTENTS: tuple[str, ...] = get_args(Intent)
OPS: tuple[str, ...] = get_args(Op)


class LookupSpec(BaseModel):
    """A known item: a title, an author's books, or both. Canonical spellings, not as typed."""

    title: str | None = None
    author: str | None = None


class ParsedRequest(BaseModel):
    intent: Intent
    semantic_query: str = ""  # mood and topic words; negated words and filter phrases removed
    lookup: LookupSpec | None = None
    seed_titles: list[str] = Field(default_factory=list)  # "like Gone Girl", catalog spelling
    seed_work_ids: list[int] = Field(default_factory=list)  # the seeds found in the catalog
    constraints: list[Constraint] = Field(default_factory=list)


@dataclass(frozen=True)
class FieldSpec:
    ops: frozenset[str]
    valid: Callable[[Any], bool]
    values: str  # what `valid` accepts, for error messages


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _scale(value: Any) -> bool:
    return _is_int(value) and 0 <= value <= 3


def _one_of(*allowed: str) -> Callable[[Any], bool]:
    return lambda value: value in allowed


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _genres(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(g in GENRES for g in value)


def _isbns(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(v, str) and len(v) == 13 and v.isdigit() for v in value)
    )


_BOUNDS = frozenset({"lt", "lte", "gt", "gte"})
_SCALE = FieldSpec(frozenset({"eq", "lte", "gte", "shift"}), _scale, "0-3")

FIELDS: dict[str, FieldSpec] = {
    "pages": FieldSpec(_BOUNDS | {"approx", "shift"}, lambda v: _is_int(v) and v > 0, "page count"),
    "year": FieldSpec(_BOUNDS | {"eq", "shift"}, lambda v: _is_int(v) and 1000 <= v <= 2100, "year"),
    "available_now": FieldSpec(frozenset({"eq"}), lambda v: v is True, "true"),
    "isbn": FieldSpec(frozenset({"in"}), _isbns, "list of ISBN-13"),
    "genre": FieldSpec(frozenset({"in"}), _genres, "list of catalog genres"),
    "facet.darkness": _SCALE,
    "facet.romance": _SCALE,
    "facet.violence": _SCALE,
    "facet.pace": FieldSpec(frozenset({"eq", "shift"}), _one_of("slow", "medium", "fast"), "slow, medium, fast"),
    "facet.supernatural": FieldSpec(frozenset({"eq"}), _one_of("yes", "no"), "yes, no"),
    "facet.historical_setting": FieldSpec(frozenset({"eq"}), _one_of("yes", "no"), "yes, no"),
    "facet.audience": FieldSpec(frozenset({"eq"}), _one_of("children", "ya", "adult"), "children, ya, adult"),
    "facet.fiction": FieldSpec(frozenset({"eq"}), lambda v: isinstance(v, bool), "true, false"),
    "facet.reading_level": FieldSpec(
        frozenset({"eq"}), _one_of("intro", "intermediate", "advanced"), "intro, intermediate, advanced"
    ),
    "theme": FieldSpec(frozenset({"eq"}), _text, "short phrase"),  # no facet for it: soft penalty
    "title": FieldSpec(frozenset({"eq"}), _text, "a book title"),  # "other than 1984"
    "popular": FieldSpec(frozenset({"eq"}), lambda v: v is True, "true"),
}  # fmt: skip


def constraint_problems(field: str, op: str, value: Any) -> list[str]:
    """Why a constraint is outside the vocabulary; empty when it's fine."""
    spec = FIELDS.get(field)
    if spec is None:
        return [f"unknown field {field!r}"]
    if op not in spec.ops:
        return [f"{field}: op {op!r} not allowed (use {', '.join(sorted(spec.ops))})"]
    if op == "shift":  # a direction relative to the books already shown
        return [] if value in (1, -1) and _is_int(value) else [f"{field}: shift takes +1 or -1"]
    if not spec.valid(value):
        return [f"{field}: bad value {value!r} (expected {spec.values})"]
    return []


def from_rules(parse: RuleParse) -> ParsedRequest:
    """The rules-only baseline: numbers, dates, availability and ISBNs, nothing else."""
    is_isbn = any(c.field == "isbn" for c in parse.constraints)
    return ParsedRequest(
        intent="lookup" if is_isbn else "discover",
        semantic_query=parse.residual,
        constraints=parse.constraints,
    )


def parse_rules_only(query: str, today: date) -> ParsedRequest:
    return from_rules(parse_rules(query, today))
