"""Import books by ISBN: look up Open Library, group editions into works, load the catalog.

    uv run python scripts/import_isbns.py data/seed/isbns.csv --source seed

The CSV needs an `isbn13` (or `isbn`) column; ISBN-10s are converted. Re-running is safe.
Rejected rows (invalid ISBN, not found, not English) go to the ingest_error table. Approved merges
in data/seed/work_merges.csv are applied afterwards (`make review-duplicates` to decide new ones).
"""

import argparse
import csv
from pathlib import Path

from sqlalchemy import insert

from shelfwise.catalog import schema
from shelfwise.catalog.db import make_engine
from shelfwise.ingest.cluster import cluster_editions
from shelfwise.ingest.load import load_clusters
from shelfwise.ingest.merges import apply_merges, find_candidates, load_decisions
from shelfwise.ingest.normalize import normalize_isbn
from shelfwise.ingest.openlibrary import OpenLibraryClient
from shelfwise.ingest.records import EditionRecord


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--source", choices=["seed", "import", "manual"], default="seed")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/openlibrary"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    with args.csv_path.open(newline="") as f:
        raw_isbns = [row.get("isbn13") or row.get("isbn") or "" for row in csv.DictReader(f)]
    raw_isbns = raw_isbns[: args.limit]

    client = OpenLibraryClient(args.cache_dir)
    records: list[EditionRecord] = []
    errors: list[dict[str, str]] = []
    for i, raw in enumerate(raw_isbns, start=1):
        isbn13 = normalize_isbn(raw)
        if isbn13 is None:
            errors.append({"record_ref": raw, "reason": "invalid ISBN"})
        elif (record := client.lookup_isbn(isbn13)) is None:
            errors.append({"record_ref": isbn13, "reason": "not found on Open Library"})
        elif record.language != "en":
            errors.append({"record_ref": isbn13, "reason": f"language {record.language}"})
        else:
            records.append(record)
        if i % 25 == 0 or i == len(raw_isbns):
            print(f"looked up {i}/{len(raw_isbns)}")

    clusters = cluster_editions(records)
    decisions = load_decisions()
    with make_engine().begin() as conn:
        if errors:
            conn.execute(
                insert(schema.ingest_error),
                [{"source": f"isbn:{args.csv_path.name}", **e} for e in errors],
            )
        stats = load_clusters(conn, clusters, source=args.source)
        merged = apply_merges(conn, decisions)
        candidates = find_candidates(conn, decisions)

    print(
        f"\n{len(records)} editions -> {len(clusters)} works "
        f"({stats.works_created} new, {stats.works_reused} already present), "
        f"{stats.editions_created} new editions, {len(errors)} rejected, "
        f"catalog_version={stats.catalog_version}"
    )
    for reason in sorted({e["reason"] for e in errors}):
        print(f"  rejected ({reason}): {sum(e['reason'] == reason for e in errors)}")
    if merged:
        print(f"  merged {merged} works as approved in data/seed/work_merges.csv")
    if candidates:
        print(f"  {len(candidates)} possible duplicate works to review: `make review-duplicates`")


if __name__ == "__main__":
    main()
