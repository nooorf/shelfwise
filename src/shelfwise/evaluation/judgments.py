"""Relevance judgments (qrels) in a hand-editable CSV.

Books are identified by `work_key` (their lowest ISBN-13), not by database id, because rebuilding
the catalog renumbers ids while ISBNs stay put. A blank grade means "pooled, not yet judged".
"""

import csv
import hashlib
from collections import defaultdict
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


def merge_pool(existing: list[Judgment], pooled: list[Judgment]) -> list[Judgment]:
    """Add newly pooled (query, book) pairs; never touch existing rows or their grades."""
    seen = {(j.query_id, j.work_key) for j in existing}
    added = [j for j in pooled if (j.query_id, j.work_key) not in seen]
    return existing + added


def qrels_by_query(judgments: list[Judgment]) -> dict[str, dict[str, int]]:
    """Graded judgments only, as {query_id: {work_key: grade}}."""
    qrels: dict[str, dict[str, int]] = defaultdict(dict)
    for j in judgments:
        if j.grade is not None:
            qrels[j.query_id][j.work_key] = j.grade
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
