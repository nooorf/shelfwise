"""Suggested book tags, reviewed as one Markdown document (like the relevance grades).

Claude suggests tags for the labelling sample from the book record alone (never from the LLM
tagger's output, which these labels exist to score). The suggestions live in
`eval/data/facet_prelabels.csv` and are not labels: a tag counts only once a person has reviewed
it. `render_doc` writes one section per book with a small table of tags; the reviewer edits values
in place; `parse_doc` reads them back. Reviewed labels are saved under the judge
"<initials>-review", so they can always be told apart from labels made from scratch.
"""

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shelfwise.tagging.labels import COLUMNS, FACET_BY_NAME, FACETS, FacetLabel

PRELABEL_COLUMNS = (*COLUMNS, "note")
CANT_TELL = "?"
NOT_APPLICABLE = "-"
BLURB_CHARS = 320

_SECTION = re.compile(r"^## \d+ · .* · (?P<key>\d{13})\s*$")
_ROW = re.compile(r"^\|\s*(?P<tag>[a-z_]+)\s*\|(?P<value>[^|]*)\|")
_ALLOWED = {
    "darkness": "0 light · 1 some serious moments · 2 dark · 3 very dark",
    "romance": "0 none · 1 minor subplot · 2 significant subplot · 3 central",
    "violence": "0 none · 1 mild or off-page · 2 on-page · 3 graphic",
    "historical_setting": "yes · no · unclear (fiction only)",
    "reading_level": "intro · intermediate · advanced · none (nonfiction only)",
}


@dataclass(frozen=True)
class PreLabel:
    label: FacetLabel
    note: str = ""


def load_prelabels(path: Path) -> list[PreLabel]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != PRELABEL_COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(PRELABEL_COLUMNS)}")
        rows = []
        for row in reader:
            labels = {s.name: v for s in FACETS if (v := (row[s.name] or "").strip())}
            label = FacetLabel(
                row["work_key"].strip(),
                row["judge"].strip(),
                labels,
                row["setting_period"] or "",
                row["title"] or "",
            )
            rows.append(PreLabel(label, row["note"] or ""))
    return rows


def save_prelabels(path: Path, rows: Iterable[PreLabel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(PRELABEL_COLUMNS)
        for p in rows:
            label = p.label
            values = [label.labels.get(s.name, "") for s in FACETS]
            writer.writerow(
                [label.work_key, label.judge, *values, label.setting_period, label.title, p.note]
            )


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def render_doc(prelabels: Sequence[PreLabel], books: Mapping[str, Any], header: str) -> str:
    """One section per book, in the order given. `books` maps work_key to a record with title,
    authors, first_pub_year, pages, genres and description."""
    lines = [header]
    for number, p in enumerate(prelabels, start=1):
        label, book = p.label, books.get(p.label.work_key)
        title = book.title if book else label.title
        lines += ["", f"## {number} · {_cell(title)} · {label.work_key}", ""]
        if book is not None:
            lines.append(
                f"**{_cell(book.authors or 'unknown author')}** · {book.first_pub_year or '?'} · "
                f"{book.pages or '?'} pages · {', '.join(book.genres) or 'no genres'}"
            )
            blurb = " ".join((book.description or "").split())
            if blurb:
                lines += [
                    "",
                    f"> {_cell(blurb[:BLURB_CHARS])}{'…' if len(blurb) > BLURB_CHARS else ''}",
                ]
        if p.note:
            lines += ["", f"*Note:* {_cell(p.note)}"]
        lines += ["", "| Tag | Value | Allowed |", "| --- | --- | --- |"]
        for spec in FACETS:
            known = {k: v for k, v in label.labels.items()}
            value = (
                label.labels.get(spec.name, CANT_TELL) if spec.applies(known) else NOT_APPLICABLE
            )
            allowed = _ALLOWED.get(spec.name, " · ".join(spec.values))
            lines.append(f"| {spec.name} | {value} | {allowed} |")
            if spec.name == "historical_setting":
                lines.append(
                    f"| setting_period | {_cell(label.setting_period)} | the era, when set in the past |"
                )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ReviewedBook:
    work_key: str
    labels: dict[str, str]
    setting_period: str


def parse_doc(text: str) -> list[ReviewedBook]:
    """Read a reviewed document back; raises ValueError listing every bad cell by line."""
    books: list[ReviewedBook] = []
    problems: list[str] = []
    key: str | None = None
    labels: dict[str, str] = {}
    period = ""

    def finish() -> None:
        if key is None:
            return
        applicable = {}
        for spec in FACETS:  # in order, so `applies` sees the answers it depends on
            if spec.name in labels and spec.applies(applicable):
                applicable[spec.name] = labels[spec.name]
        keep_period = applicable.get("historical_setting") == "yes"
        books.append(ReviewedBook(key, applicable, period if keep_period else ""))

    for number, line in enumerate(text.splitlines(), start=1):
        if match := _SECTION.match(line):
            finish()
            key, labels, period = match["key"], {}, ""
            continue
        row = _ROW.match(line)
        if key is None or row is None or row["tag"] == "tag":
            continue
        tag, value = row["tag"], row["value"].strip()
        if tag == "setting_period":
            period = value.replace("\\|", "|")
            continue
        spec = FACET_BY_NAME.get(tag)
        if spec is None:
            problems.append(f"line {number}: unknown tag {tag!r}")
        elif value in ("", CANT_TELL, NOT_APPLICABLE):
            continue
        elif value not in spec.values:
            problems.append(f"line {number}: {tag} must be one of {', '.join(spec.values)} (or ?)")
        else:
            labels[tag] = value
    finish()
    if problems:
        raise ValueError("\n  ".join(["fix these in the document first:", *problems]))
    return books
