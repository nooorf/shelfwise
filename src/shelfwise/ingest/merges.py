"""Human-approved merges of works the importer split apart (design doc §10).

Open Library sometimes files editions of one book as separate works (*Hands-On Machine Learning*
1st vs 2nd edition), and similar titles by one author are often different books (*Haunting Adeline*
and its sequel *Hunting Adeline*). So near-duplicates are never merged automatically: a person
decides each pair once, the decision is kept in `data/seed/work_merges.csv` keyed by ISBN, and
`apply_merges` replays the "merge" decisions after every import.
"""

import csv
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, cast

from rapidfuzz import fuzz
from sqlalchemy import Connection, text

from shelfwise.catalog.availability import refresh_availability_view
from shelfwise.catalog.meta import bump_catalog_version
from shelfwise.ingest.normalize import title_norm

MERGES = Path("data/seed/work_merges.csv")
COLUMNS = ("keep_isbn", "other_isbn", "decision", "keep_title", "other_title")
NEAR_IDENTICAL = 95  # rapidfuzz ratio of normalized full titles ("Haunting" / "Hunting Adeline")
_SUBTITLE = re.compile(r":|,|\s\(|\s-\s")
_NUMBER = re.compile(r"\d+")

type Decision = Literal["merge", "separate"]


@dataclass(frozen=True)
class MergeDecision:
    keep_isbn: str  # any edition of the work that survives (its title and fields are kept)
    other_isbn: str  # any edition of the work folded into it
    decision: Decision
    keep_title: str = ""
    other_title: str = ""


@dataclass(frozen=True)
class Candidate:
    work_a: int
    work_b: int
    isbn_a: str
    isbn_b: str
    title_a: str
    title_b: str
    author: str
    score: float


def load_decisions(path: Path = MERGES) -> list[MergeDecision]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}")
        rows, problems = [], []
        for line, row in enumerate(reader, start=2):
            decision = row["decision"].strip()
            if decision not in ("merge", "separate"):
                problems.append(f"line {line}: decision must be merge or separate")
                continue
            rows.append(
                MergeDecision(
                    row["keep_isbn"].strip(),
                    row["other_isbn"].strip(),
                    cast(Decision, decision),
                    row["keep_title"] or "",
                    row["other_title"] or "",
                )
            )
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return rows


def save_decisions(path: Path, decisions: Iterable[MergeDecision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for d in decisions:
            writer.writerow([d.keep_isbn, d.other_isbn, d.decision, d.keep_title, d.other_title])
    tmp.replace(path)


def title_similarity(a: str, b: str) -> float | None:
    """How likely two titles by one author name the same book (0-100), or None if unlikely.

    Same main title ("Elon Musk" / "Elon Musk: Inventing the Future", "The Stand (Library
    Edition)") or near-identical full titles count. Different numbers never do: "Vol. 4" / "Vol. 6"
    are different books, and so are two different subtitles of one franchise ("Batman: Hush" /
    "Batman: Year One"). Sequels that extend a title ("Hannibal" / "Hannibal Rising") don't count.
    """
    if set(_NUMBER.findall(a)) != set(_NUMBER.findall(b)):
        return None
    parts_a, parts_b = _SUBTITLE.split(a, maxsplit=1), _SUBTITLE.split(b, maxsplit=1)
    one_subtitle = len(parts_a) == 1 or len(parts_b) == 1  # "Batman: Hush" / "Batman: Year One"
    if one_subtitle and title_norm(parts_a[0]) == title_norm(parts_b[0]):
        return 100.0
    score = fuzz.ratio(title_norm(a), title_norm(b))
    return score if score >= NEAR_IDENTICAL else None


def _work_of_isbn(conn: Connection) -> dict[str, int]:
    rows = conn.execute(text("SELECT isbn13, work_id FROM edition WHERE isbn13 IS NOT NULL"))
    return {r.isbn13: r.work_id for r in rows}


_WORKS_SQL = text(
    """
    SELECT w.work_id, w.title, a.name_norm AS author_key, a.display AS author,
           (SELECT min(e.isbn13) FROM edition e WHERE e.work_id = w.work_id) AS isbn
    FROM work w
    JOIN work_author wa ON wa.work_id = w.work_id AND wa.position = 1
    JOIN author a USING (author_id)
    ORDER BY w.work_id
    """
)


def find_candidates(conn: Connection, decisions: Sequence[MergeDecision]) -> list[Candidate]:
    """Undecided pairs of works with near-identical titles by the same first author."""
    work_of = _work_of_isbn(conn)
    decided = {frozenset((work_of.get(d.keep_isbn), work_of.get(d.other_isbn))) for d in decisions}
    by_author: dict[str, list[Any]] = {}
    for r in conn.execute(_WORKS_SQL):
        if r.isbn:  # decisions are keyed by ISBN
            by_author.setdefault(r.author_key, []).append(r)
    return [
        Candidate(a.work_id, b.work_id, a.isbn, b.isbn, a.title, b.title, a.author, score)
        for group in by_author.values()
        for a, b in combinations(group, 2)
        if frozenset((a.work_id, b.work_id)) not in decided
        and (score := title_similarity(a.title, b.title)) is not None
    ]


def merge_work(conn: Connection, keep_id: int, other_id: int) -> None:
    """Fold `other_id` into `keep_id`: editions (with their copies and loans) move over, gaps in
    the kept work's record are filled from the other, then the other work is deleted."""
    params = {"keep": keep_id, "other": other_id}
    conn.execute(text("UPDATE edition SET work_id = :keep WHERE work_id = :other"), params)
    conn.execute(
        text(
            """
            UPDATE work k SET
                description = coalesce(k.description, o.description),
                description_source = CASE WHEN k.description IS NULL
                                          THEN o.description_source ELSE k.description_source END,
                low_info = k.low_info AND o.low_info,
                first_pub_year = least(k.first_pub_year, o.first_pub_year),
                genres = ARRAY(SELECT DISTINCT unnest(k.genres || o.genres)),
                tags = ARRAY(SELECT DISTINCT unnest(k.tags || o.tags)),
                popularity = greatest(k.popularity, o.popularity),
                updated_at = now()
            FROM work o
            WHERE k.work_id = :keep AND o.work_id = :other
            """
        ),
        params,
    )
    # Keep the other work's tags only if the kept one has none (a human label is never lost).
    conn.execute(
        text(
            """
            UPDATE work_facets SET work_id = :keep
            WHERE work_id = :other
              AND NOT EXISTS (SELECT 1 FROM work_facets WHERE work_id = :keep)
            """
        ),
        params,
    )
    conn.execute(text("DELETE FROM work WHERE work_id = :other"), params)


def apply_merges(conn: Connection, decisions: Sequence[MergeDecision]) -> int:
    """Replay every "merge" decision whose works are still separate; returns how many merged.

    Idempotent. Decisions whose ISBNs aren't in the catalog (yet) are skipped.
    """
    merged = 0
    for d in decisions:
        if d.decision != "merge":
            continue
        work_of = _work_of_isbn(conn)  # re-read: an earlier merge may have moved editions
        keep, other = work_of.get(d.keep_isbn), work_of.get(d.other_isbn)
        if keep is None or other is None or keep == other:
            continue
        merge_work(conn, keep, other)
        merged += 1
    if merged:
        refresh_availability_view(conn)
        bump_catalog_version(conn)
    return merged
