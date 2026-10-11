"""The landing page's featured shelf: popular books with a real cover.

`scripts/pick_featured.py` chooses them and looks up each one's Open Library cover id once;
the list is kept in `data/seed/featured.csv` keyed by work key (the lowest ISBN-13, stable
across catalog rebuilds), so it can be edited by hand. Covers are served by id, which Open
Library doesn't rate-limit (lookups by ISBN are: 100 per 5 minutes per IP).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, text

FEATURED = Path("data/seed/featured.csv")
COLUMNS = ("work_key", "cover_id", "title")


@dataclass(frozen=True)
class Featured:
    work_key: str
    cover_id: int
    title: str = ""  # for reading the file; the catalog's title is what's shown


def load_featured(path: Path = FEATURED) -> list[Featured]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: expected columns {', '.join(COLUMNS)}")
        return [Featured(r["work_key"], int(r["cover_id"]), r["title"]) for r in reader]


def save_featured(rows: list[Featured], path: Path = FEATURED) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows((r.work_key, r.cover_id, r.title) for r in rows)


def featured_works(conn: Connection, rows: list[Featured]) -> list[tuple[int, int]]:
    """(work_id, cover_id) in the file's order, skipping books no longer in the catalog."""
    keys = [r.work_key for r in rows]
    found = conn.execute(
        text(
            "SELECT work_id, min(isbn13) AS key FROM edition GROUP BY work_id "
            "HAVING min(isbn13) = ANY(:keys)"
        ),
        {"keys": keys},
    )
    ids = {r.key: r.work_id for r in found}
    return [(ids[r.work_key], r.cover_id) for r in rows if r.work_key in ids]
