"""The constraint model shared by the rule parser, the LLM parser and UI chips."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

Op = Literal["eq", "in", "lt", "lte", "gt", "gte", "not_in", "approx", "shift"]
Strength = Literal["hard", "soft"]
Source = Literal["rule", "llm", "chip", "state"]

# Fields with numeric ranges, checked for contradictions.
NUMERIC_FIELDS = ("pages", "year")


class Constraint(BaseModel):
    """One requirement or preference.

    `field` names what is constrained: "pages", "year" (the work's original publication year),
    "available_now", "isbn", "genre", "facet.supernatural", ...
    """

    field: str
    op: Op
    value: Any
    strength: Strength
    source: Source
    polarity: Literal["include", "exclude"] = "include"
    span: str | None = None  # the words it came from: shown as a chip, used for debugging


@dataclass(frozen=True)
class Contradiction:
    field: str
    spans: tuple[str, ...]

    def message(self) -> str:
        return f"{self.field}: " + " and ".join(repr(s) for s in self.spans) + " can't both hold"


def _bounds(constraint: Constraint) -> tuple[float, float] | None:
    value = constraint.value
    match constraint.op:
        case "lt":
            return float("-inf"), value - 1
        case "lte":
            return float("-inf"), value
        case "gt":
            return value + 1, float("inf")
        case "gte":
            return value, float("inf")
        case "eq":
            return value, value
    return None


def contradictions(constraints: list[Constraint]) -> list[Contradiction]:
    """Hard numeric constraints on one field that no value can satisfy together."""
    found = []
    for field in NUMERIC_FIELDS:
        hard = [
            (c, b)
            for c in constraints
            if c.field == field and c.strength == "hard" and (b := _bounds(c)) is not None
        ]
        low = max((b[0] for _, b in hard), default=float("-inf"))
        high = min((b[1] for _, b in hard), default=float("inf"))
        if low > high:
            spans = tuple(c.span or f"{c.op} {c.value}" for c, _ in hard)
            found.append(Contradiction(field, spans))
    return found
