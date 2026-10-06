"""Evaluation query set A (design doc §27). Loaded from a hand-edited CSV and validated strictly."""

import csv
from dataclasses import dataclass
from pathlib import Path

CATEGORIES = (
    "lookup",
    "author",
    "genre",
    "discovery",
    "multi_constraint",
    "negation",
    "availability",
    "similarity",
    "vague",
    "adversarial",
    "learning",  # topic + reader level + goal: "from scratch", "interview ready", "for my course"
)
PERSONAS = ("student", "casual", "researcher", "librarian", "visitor")
# llm-draft: written by an LLM; persona: written by a team member; real: collected from people;
# synthetic: generated from a book record. Metrics are reported per source.
SOURCES = ("llm-draft", "persona", "real", "synthetic")
COLUMNS = ("id", "category", "persona", "family", "source", "text", "notes")


@dataclass(frozen=True)
class Query:
    id: str
    category: str
    persona: str
    family: str  # paraphrases of one need share a family and always land in the same split
    source: str
    text: str
    notes: str = ""


def load_queries(path: Path) -> list[Query]:
    """Load and validate; raises ValueError listing every problem, with line numbers."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}")
        rows = list(reader)

    problems: list[str] = []
    queries: list[Query] = []
    seen_ids: set[str] = set()
    for line, row in enumerate(rows, start=2):
        values = {k: (row.get(k) or "").strip() for k in COLUMNS}
        query = Query(**values)
        if not query.id:
            problems.append(f"line {line}: missing id")
        elif query.id in seen_ids:
            problems.append(f"line {line}: duplicate id {query.id}")
        seen_ids.add(query.id)
        if query.category not in CATEGORIES:
            problems.append(f"line {line}: unknown category {query.category!r}")
        if query.persona not in PERSONAS:
            problems.append(f"line {line}: unknown persona {query.persona!r}")
        if query.source not in SOURCES:
            problems.append(f"line {line}: unknown source {query.source!r}")
        if not query.family:
            problems.append(f"line {line}: missing family")
        if not query.text:
            problems.append(f"line {line}: empty text")
        queries.append(query)

    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return queries
