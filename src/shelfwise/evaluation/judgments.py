"""Relevance judgments (qrels) in a hand-editable CSV.

Books are identified by `work_key` (their lowest ISBN-13), not by database id, because rebuilding
the catalog renumbers ids while ISBNs stay put. A blank grade means "pooled, not yet judged".

Pre-labels (an LLM's suggested grades with a one-line reason) live in their own file and only
become judgments when a person reviews them; see GRADING.md.

Merging two works (merges.py) can change the merged work's key. Saved grades are never rewritten;
readers resolve old keys through `key_aliases` instead.
"""

import csv
import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import Connection, text

GRADES = (0, 1, 2, 3)
COLUMNS = ("query_id", "work_key", "grade", "judge", "title", "author")


@dataclass(frozen=True)
class Judgment:
    query_id: str
    work_key: str
    grade: int | None = None
    judge: str = ""  # who graded it: a name/initials, or "llm" for pre-labels (Phase 3)
    title: str = ""
    author: str = ""


@dataclass(frozen=True)
class PreLabel:
    query_id: str
    work_key: str
    grade: int
    judge: str  # who suggested it, e.g. "claude"
    reason: str = ""


PRELABEL_COLUMNS = ("query_id", "work_key", "grade", "judge", "reason")


def load_prelabels(path: Path) -> list[PreLabel]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != PRELABEL_COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(PRELABEL_COLUMNS)}")
        rows = []
        for line, row in enumerate(reader, start=2):
            if row["grade"].strip() not in {str(g) for g in GRADES}:
                raise ValueError(f"{path}: line {line}: grade must be 0-3")
            rows.append(
                PreLabel(
                    row["query_id"].strip(),
                    row["work_key"].strip(),
                    int(row["grade"]),
                    row["judge"].strip(),
                    row["reason"] or "",
                )
            )
    return rows


def save_prelabels(path: Path, rows: list[PreLabel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(PRELABEL_COLUMNS)
        for r in rows:
            writer.writerow([r.query_id, r.work_key, r.grade, r.judge, r.reason])
    tmp.replace(path)


def load_judgments(path: Path) -> list[Judgment]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}")
        judgments, problems = [], []
        for line, row in enumerate(reader, start=2):
            raw = (row["grade"] or "").strip()
            if raw and raw not in {str(g) for g in GRADES}:
                problems.append(f"line {line}: grade must be 0-3 or blank, got {raw!r}")
                continue
            judgments.append(
                Judgment(
                    query_id=row["query_id"].strip(),
                    work_key=row["work_key"].strip(),
                    grade=int(raw) if raw else None,
                    judge=(row["judge"] or "").strip(),
                    title=row["title"] or "",
                    author=row["author"] or "",
                )
            )
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return judgments


def save_judgments(path: Path, judgments: list[Judgment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for j in judgments:
            writer.writerow(
                [
                    j.query_id,
                    j.work_key,
                    "" if j.grade is None else j.grade,
                    j.judge,
                    j.title,
                    j.author,
                ]
            )
    tmp.replace(path)  # atomic: a crash mid-write never corrupts the file


def merge_pool(
    existing: list[Judgment], pooled: list[Judgment], aliases: Mapping[str, str] | None = None
) -> list[Judgment]:
    """Add newly pooled (query, book) pairs; never touch existing rows or their grades."""
    aliases = aliases or {}
    seen = {(j.query_id, aliases.get(j.work_key, j.work_key)) for j in existing}
    added = [j for j in pooled if (j.query_id, j.work_key) not in seen]
    return existing + added


def drop_stale(
    judgments: list[Judgment],
    pooled: list[Judgment],
    aliases: Mapping[str, str] | None = None,
) -> list[Judgment]:
    """Remove ungraded pairs that no system returns any more (e.g. after the catalog grew).

    Grades are never removed: a graded book that has dropped out of every top 10 can climb back
    with a better system, and its grade is still a valid judgment.
    """
    aliases = aliases or {}
    current = {(j.query_id, aliases.get(j.work_key, j.work_key)) for j in pooled}
    return [
        j
        for j in judgments
        if j.grade is not None or (j.query_id, aliases.get(j.work_key, j.work_key)) in current
    ]


def qrels_by_query(
    judgments: list[Judgment], aliases: Mapping[str, str] | None = None
) -> dict[str, dict[str, int]]:
    """Graded judgments only, as {query_id: {work_key: grade}}, keys resolved through `aliases`.

    Two grades for one book (graded as separate works before a merge) keep the higher one: any
    edition of the right book deserves the same grade (GRADING.md).
    """
    aliases = aliases or {}
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    for j in judgments:
        if j.grade is not None:
            key = aliases.get(j.work_key, j.work_key)
            qrels[j.query_id][key] = max(j.grade, qrels[j.query_id].get(key, 0))
    return dict(qrels)


def set_grade(
    judgments: list[Judgment], index: int, grade: int | None, judge: str
) -> list[Judgment]:
    updated = list(judgments)
    updated[index] = replace(updated[index], grade=grade, judge=judge if grade is not None else "")
    return updated


def work_keys(conn: Connection) -> dict[int, str]:
    """work_id -> stable key: the lowest ISBN-13 among its editions (or a title hash fallback)."""
    rows = conn.execute(
        text(
            "SELECT w.work_id, w.title_norm, min(e.isbn13) AS isbn "
            "FROM work w LEFT JOIN edition e USING (work_id) GROUP BY w.work_id"
        )
    )
    return {
        r.work_id: r.isbn or "t:" + hashlib.sha1(r.title_norm.encode()).hexdigest()[:12]
        for r in rows
    }


def key_aliases(conn: Connection) -> dict[str, str]:
    """Every edition's ISBN-13, and every current key, -> the current key of its work."""
    keys = work_keys(conn)
    aliases = {key: key for key in keys.values()}
    for r in conn.execute(text("SELECT isbn13, work_id FROM edition WHERE isbn13 IS NOT NULL")):
        aliases[r.isbn13] = keys[r.work_id]
    return aliases
