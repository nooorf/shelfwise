"""What the LLM may know about each book it talks about (design doc §18.2, grounded context).

One compact record per book, built from the catalog: title, authors, pages, year, genres, the
tags, which of the person's wishes the book meets, and the start of the description. The same
records are what the validator checks the LLM's words against, so "only facts in the record" is
something code can test.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from shelfwise.query.constraints import Constraint
from shelfwise.ranking.soft import facet_match

DESCRIPTION_CHARS = 600
_FACET_KEYS = ("darkness", "romance", "violence", "pace", "supernatural", "audience", "fiction")


@dataclass(frozen=True)
class Candidate:
    work_id: int
    title: str
    authors: list[str]
    pages: int | None
    year: int | None
    genres: list[str]
    facets: dict[str, Any] = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)  # the wishes it meets, as chip labels
    description: str = ""

    def as_record(self) -> dict[str, Any]:
        """The JSON the LLM sees: nothing empty, nothing it shouldn't repeat as fact."""
        record: dict[str, Any] = {"work_id": self.work_id, "title": self.title}
        if self.authors:
            record["author"] = ", ".join(self.authors)
        for key in ("pages", "year"):
            if (value := getattr(self, key)) is not None:
                record[key] = value
        if self.genres:
            record["genres"] = self.genres[:4]
        if facets := {k: v for k, v in self.facets.items() if k in _FACET_KEYS and v is not None}:
            record["tags"] = facets
        if self.matched:
            record["matches"] = self.matched
        if self.description:
            record["description"] = self.description
        return record

    @property
    def record_text(self) -> str:
        """Everything the record says, for checking numbers and claim words against."""
        return " ".join(
            [self.title, *self.authors, *self.genres, self.description,
             str(self.pages or ""), str(self.year or "")]
        )  # fmt: skip


def matched_labels(
    constraints: list[tuple[str, Constraint]], facets: dict[str, Any], genres: list[str]
) -> list[str]:
    """Labels of the (label, constraint) pairs this book meets. Hard filters are met by
    construction (it passed them); soft ones are checked against its tags and genres."""
    met = []
    for label, c in constraints:
        if c.op == "shift":
            continue
        if c.strength == "hard":
            met.append(label)
        elif c.field.startswith("facet."):
            if facet_match(c, facets.get(c.field.removeprefix("facet."))) > 0:
                met.append(label)
        elif c.field == "genre" and c.polarity == "include":
            values = c.value if isinstance(c.value, list) else [c.value]
            if set(values) & set(genres):
                met.append(label)
    return list(dict.fromkeys(met))


_DESCRIPTIONS = text(
    "SELECT work_id, coalesce(description, '') AS d FROM work WHERE work_id = ANY(:ids)"
)


def descriptions(conn: Connection, ids: list[int]) -> dict[int, str]:
    rows = conn.execute(_DESCRIPTIONS, {"ids": ids})
    return {r.work_id: " ".join(r.d.split())[:DESCRIPTION_CHARS] for r in rows}
