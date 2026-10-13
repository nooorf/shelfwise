"""Parser gold set B: the ideal parse of each query, hand-checked.

Lives in `eval/data/parser_gold.yaml`. Rules for writing it: `eval/PARSING.md`. Every query of set A
has a gold parse (its text, category and family come from `queries.csv`); set B adds its own
queries, which carry those columns themselves.

Constraints are written one per line so they're quick to review:

    [not] <field> <op> <value> <hard|soft>

    pages lt 300 hard
    genre in [mystery, thriller] soft
    not facet.supernatural eq yes hard      # "not" = polarity exclude
    not theme eq animal deaths soft         # the value may contain spaces

Titles, authors, seeds and keep/drop phrases accept alternatives separated by " | ".
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from shelfwise.evaluation.queries import CATEGORIES, SOURCES, load_queries
from shelfwise.query.request import INTENTS, OPS, constraint_problems

# Single-message parser categories that set A doesn't have.
B_CATEGORIES = (*CATEGORIES, "refinement", "followup", "other")
_PARSE_KEYS = {"intent", "lookup", "seeds", "constraints", "keep", "drop", "notes"}
_QUERY_KEYS = {"text", "category", "family", "source"}  # only for queries that aren't in set A


@dataclass(frozen=True)
class GoldConstraint:
    field: str
    op: str
    value: Any
    strength: str
    polarity: str = "include"

    def __str__(self) -> str:
        value = (
            f"[{', '.join(map(str, self.value))}]" if isinstance(self.value, list) else self.value
        )
        value = str(value).lower() if isinstance(value, bool) else value
        prefix = "not " if self.polarity == "exclude" else ""
        return f"{prefix}{self.field} {self.op} {value} {self.strength}"


@dataclass(frozen=True)
class GoldParse:
    id: str
    text: str
    category: str
    family: str
    source: str
    intent: str
    title: str | None = None  # lookup title, alternatives split by " | "
    author: str | None = None
    seeds: tuple[str, ...] = ()
    constraints: tuple[GoldConstraint, ...] = ()
    keep: tuple[str, ...] = ()  # must survive into semantic_query
    drop: tuple[str, ...] = ()  # must not: negated words
    notes: str = ""
    in_set_a: bool = field(default=True, compare=False)


@dataclass(frozen=True)
class GoldSet:
    today: date  # relative dates ("the last 10 years") resolve against this day
    queries: list[GoldParse]


def _value(text: str) -> Any:
    if text.startswith("[") and text.endswith("]"):
        return [_value(part.strip()) for part in text[1:-1].split(",") if part.strip()]
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        return text


def parse_constraint(spec: str) -> GoldConstraint:
    """'not facet.supernatural eq yes hard' -> GoldConstraint; raises ValueError."""
    words = spec.split()
    polarity = "include"
    if words[:1] == ["not"]:
        polarity, words = "exclude", words[1:]
    if len(words) < 4:
        raise ValueError(f"{spec!r}: expected '[not] field op value hard|soft'")
    name, op, *value_words, strength = words
    if op not in OPS:
        raise ValueError(f"{spec!r}: unknown op {op!r}")
    if strength not in ("hard", "soft"):
        raise ValueError(f"{spec!r}: strength must be hard or soft")
    value = _value(" ".join(value_words))
    if name == "isbn" and isinstance(value, list):
        value = [str(v) for v in value]  # an ISBN is an identifier, not a number
    if problems := constraint_problems(name, op, value):
        raise ValueError(f"{spec!r}: {'; '.join(problems)}")
    return GoldConstraint(name, op, value, strength, polarity)


def _strings(row: dict[str, Any], key: str) -> tuple[str, ...]:
    value = row.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, str | int) for v in value):
        raise ValueError(f"{key} must be a list of strings")
    return tuple(str(v) for v in value)


def _gold(row: dict[str, Any], set_a: dict[str, Any]) -> GoldParse:
    query_id = str(row.get("id") or "")
    if not query_id:
        raise ValueError("missing id")
    in_set_a = query_id in set_a
    unknown = set(row) - _PARSE_KEYS - _QUERY_KEYS - {"id"}
    if unknown:
        raise ValueError(f"unknown keys {sorted(unknown)}")
    if in_set_a:
        if given := sorted(_QUERY_KEYS & set(row)):
            raise ValueError(f"{given} come from queries.csv for set A queries")
        query = set_a[query_id]
        text, category, family, source = query.text, query.category, query.family, query.source
    else:
        if missing := sorted({"text", "category", "source"} - set(row)):
            raise ValueError(f"not in set A, so it needs {missing}")
        text, category, source = str(row["text"]), row["category"], row["source"]
        family = str(row.get("family") or query_id)
        if category not in B_CATEGORIES:
            raise ValueError(f"unknown category {category!r}")
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
    if row.get("intent") not in INTENTS:
        raise ValueError(f"intent must be one of {', '.join(INTENTS)}")
    lookup = row.get("lookup") or {}
    if not isinstance(lookup, dict) or set(lookup) - {"title", "author"}:
        raise ValueError("lookup takes title and/or author")
    specs = row.get("constraints") or []
    if not isinstance(specs, list):
        raise ValueError("constraints must be a list")
    return GoldParse(
        id=query_id,
        text=text,
        category=category,
        family=family,
        source=source,
        intent=row["intent"],
        title=str(lookup["title"]) if lookup.get("title") else None,
        author=str(lookup["author"]) if lookup.get("author") else None,
        seeds=_strings(row, "seeds"),
        constraints=tuple(parse_constraint(str(s)) for s in specs),
        keep=_strings(row, "keep"),
        drop=_strings(row, "drop"),
        notes=str(row.get("notes") or ""),
        in_set_a=in_set_a,
    )


def load_gold(path: Path, queries_csv: Path) -> GoldSet:
    """Load and validate; raises ValueError listing every problem by query id."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("today"), date):
        raise ValueError(f"{path}: needs 'today: YYYY-MM-DD' and a 'queries' list")
    set_a = {q.id: q for q in load_queries(queries_csv)}
    problems: list[str] = []
    golds: list[GoldParse] = []
    seen: set[str] = set()
    for position, row in enumerate(data.get("queries") or [], start=1):
        label = str(row.get("id") or f"#{position}") if isinstance(row, dict) else f"#{position}"
        if label in seen:
            problems.append(f"{label}: duplicate id")
        seen.add(label)
        try:
            golds.append(_gold(row, set_a))
        except (ValueError, TypeError, AttributeError) as error:
            problems.append(f"{label}: {error}")
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return GoldSet(today=data["today"], queries=golds)
