"""Build the bulk catalog from the UCSD Book Graph genre subsets (Goodreads, 2017).

    make download-goodreads                                  # ~1.6 GB into data/raw/goodreads/
    uv run python scripts/build_catalog.py --dry-run         # what would be imported, no DB
    uv run python scripts/build_catalog.py                   # ~5,000 works
    uv run python scripts/build_catalog.py --total 8000

Per genre subset, keeps the most-rated works that pass the quality checks (English, ISBN, page
count, description, not audio), one edition per work, each work counted in one subset only.
Additive and safe to re-run: books already in the catalog (same ISBN, or same title and first
author) are reused. Then run `make embed`, `make simulate` and `make tag`.
"""

import argparse
import time
from collections import Counter
from pathlib import Path
from typing import Any

from shelfwise.catalog.db import make_engine
from shelfwise.ingest.cluster import cluster_editions
from shelfwise.ingest.goodreads import (
    SUBSETS,
    file_name,
    iter_json_gz,
    quotas,
    rejection,
    to_record,
)
from shelfwise.ingest.load import load_clusters
from shelfwise.ingest.merges import apply_merges, find_candidates, load_decisions
from shelfwise.ingest.records import EditionRecord

RAW = Path("data/raw/goodreads")
AUTHORS = "goodreads_book_authors.json.gz"
WORKS = "goodreads_book_works.json.gz"
_KEEP_FIELDS = (
    "work_id", "isbn", "isbn13", "title", "title_without_series", "authors", "publisher",
    "publication_year", "num_pages", "format", "description", "popular_shelves",
)  # fmt: skip
LATEST_YEAR = 2017  # the data was collected in late 2017


def _int(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def scan_subset(path: Path, rejected: Counter[str]) -> dict[str, tuple[int, dict[str, Any]]]:
    """Usable editions in one subset: {work_id: (edition ratings, slim record)}, best edition."""
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for book in iter_json_gz(path):
        if reason := rejection(book):
            rejected[reason] += 1
            continue
        ratings = _int(book.get("ratings_count"))
        if book["work_id"] not in best or ratings > best[book["work_id"]][0]:
            best[book["work_id"]] = (ratings, {k: book.get(k) for k in _KEEP_FIELDS})
    return best


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument("--total", type=int, default=5000, help="works to import")
    parser.add_argument("--dry-run", action="store_true", help="report only; don't touch the DB")
    args = parser.parse_args()

    files = [file_name(s) for s in SUBSETS] + [AUTHORS, WORKS]
    missing = [f for f in files if not (args.raw_dir / f).exists()]
    if missing:
        raise SystemExit(
            f"Missing {', '.join(missing)} in {args.raw_dir}: run `make download-goodreads`."
        )

    start = time.perf_counter()
    rejected: Counter[str] = Counter()
    candidates: dict[str, dict[str, tuple[int, dict[str, Any]]]] = {}
    for subset in SUBSETS:
        candidates[subset] = scan_subset(args.raw_dir / file_name(subset), rejected)
        print(f"  {subset:24} {len(candidates[subset]):7,} usable works "
              f"({time.perf_counter() - start:.0f}s)")  # fmt: skip

    wanted = {wid for found in candidates.values() for wid in found}
    work_ratings: dict[str, int] = {}
    first_year: dict[str, int] = {}
    for work in iter_json_gz(args.raw_dir / WORKS):
        if (wid := work["work_id"]) in wanted:
            work_ratings[wid] = _int(work.get("ratings_count"))
            if 1000 <= (year := _int(work.get("original_publication_year"))) <= LATEST_YEAR:
                first_year[wid] = year

    chosen: dict[str, dict[str, Any]] = {}
    per_subset: dict[str, int] = {}
    for subset, quota in quotas(args.total).items():
        found = candidates[subset]
        ranked = sorted(
            (wid for wid in found if wid not in chosen),
            key=lambda wid: (work_ratings.get(wid, found[wid][0]), wid),
            reverse=True,
        )[:quota]
        chosen |= {wid: found[wid][1] for wid in ranked}
        per_subset[subset] = len(ranked)

    author_ids = {a["author_id"] for book in chosen.values() for a in book["authors"]}
    author_names = {
        a["author_id"]: a["name"].strip()
        for a in iter_json_gz(args.raw_dir / AUTHORS)
        if a["author_id"] in author_ids
    }
    records: list[EditionRecord] = [
        record
        for wid, book in chosen.items()
        if (record := to_record(book, author_names, first_year.get(wid)))
    ]

    print(f"\nrejected editions: {dict(rejected.most_common())}")
    print(f"selected: {per_subset} -> {len(records)} works with known authors")
    if args.dry_run:
        for record in records[:: max(len(records) // 8, 1)][:8]:
            print(f"  e.g. {record.title} — {', '.join(record.authors)} "
                  f"({record.first_pub_year}, {record.pages} pp): {record.subjects[:6]}")  # fmt: skip
        return

    clusters = cluster_editions(records)
    decisions = load_decisions()
    with make_engine().begin() as conn:
        stats = load_clusters(conn, clusters, source="import")
        merged = apply_merges(conn, decisions)
        review = find_candidates(conn, decisions)
    print(
        f"\n{len(clusters)} works: {stats.works_created} new, {stats.works_reused} already "
        f"present; {stats.editions_created} new editions; catalog_version={stats.catalog_version}"
    )
    if merged:
        print(f"  merged {merged} works as approved in data/seed/work_merges.csv")
    if review:
        print(f"  {len(review)} possible duplicate works to review: `make review-duplicates`")
    print(f"done in {time.perf_counter() - start:.0f}s. next: make embed, make simulate, make tag")


if __name__ == "__main__":
    main()
