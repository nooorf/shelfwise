"""Group editions into works (design doc §10).

Two editions belong to the same work if they share a source work key (Open Library already groups
editions) or the same normalized title + primary author. Near-identical titles by the same author
are never merged here: a person reviews them (see merges.py).
"""

from dataclasses import dataclass, field

from shelfwise.ingest.normalize import normalize_author, title_norm
from shelfwise.ingest.records import EditionRecord


@dataclass
class WorkCluster:
    editions: list[EditionRecord] = field(default_factory=list)

    @property
    def _primary(self) -> EditionRecord:
        # Prefer the edition with the richest record as the source of work-level fields.
        return max(self.editions, key=lambda e: (e.description is not None, len(e.subjects)))

    @property
    def title(self) -> str:
        return self._primary.title

    @property
    def subtitle(self) -> str | None:
        return self._primary.subtitle

    @property
    def title_norm(self) -> str:
        return title_norm(self.title)

    @property
    def authors(self) -> list[str]:
        return self._primary.authors

    @property
    def description(self) -> str | None:
        descriptions = [e.description for e in self.editions if e.description]
        return max(descriptions, key=len) if descriptions else None

    @property
    def subjects(self) -> list[str]:
        return list(dict.fromkeys(s for e in self.editions for s in e.subjects))

    @property
    def first_pub_year(self) -> int | None:
        years = [y for e in self.editions for y in (e.first_pub_year, e.pub_year) if y]
        return min(years) if years else None

    @property
    def isbns(self) -> list[str]:
        return [e.isbn13 for e in self.editions]


def _author_key(record: EditionRecord) -> str:
    return normalize_author(record.authors[0])[1] if record.authors else ""


def cluster_editions(
    records: list[EditionRecord],
) -> list[WorkCluster]:
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_seen: dict[tuple[str, str], int] = {}
    for i, record in enumerate(records):
        keys = [("title_author", f"{title_norm(record.title)}|{_author_key(record)}")]
        if record.source_work_key:
            keys.append(("work", record.source_work_key))
        for key in keys:
            if key in first_seen:
                parent[find(i)] = find(first_seen[key])
            else:
                first_seen[key] = i

    groups: dict[int, WorkCluster] = {}
    for i, record in enumerate(records):
        groups.setdefault(find(i), WorkCluster()).editions.append(record)
    return list(groups.values())
