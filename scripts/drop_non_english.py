"""Remove non-English books from the catalog (see shelfwise/ingest/language.py for the rules).

    uv run python scripts/drop_non_english.py            # list what would go
    uv run python scripts/drop_non_english.py --apply    # remove them

Stop `make tag` first: it would crash on a book removed mid-run. Removed books are logged to
ingest_error; their copies, loans, tags and embeddings go with them. Grades for them stay in
eval/data/qrels.csv and are ignored by the evaluation. Then run `make build-catalog` to backfill
the Goodreads slots with English books.
"""

import argparse

from sqlalchemy import insert, text

from shelfwise.catalog import schema
from shelfwise.catalog.availability import refresh_availability_view
from shelfwise.catalog.db import make_engine
from shelfwise.catalog.meta import bump_catalog_version
from shelfwise.ingest.language import find_non_english, load_excluded


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="remove them (default: list only)")
    args = parser.parse_args()

    with make_engine().begin() as conn:
        found = find_non_english(conn, load_excluded())
        for work_id, title, reason in found:
            print(f"  {work_id:6}  {title[:50]:50}  {reason}")
        if not args.apply:
            print(f"\n{len(found)} non-English books; run with --apply to remove them.")
            return
        if found:
            conn.execute(
                insert(schema.ingest_error),
                [
                    {"source": "language-check", "record_ref": str(w), "reason": f"{t}: {r}"}
                    for w, t, r in found
                ],
            )
            conn.execute(
                text("DELETE FROM work WHERE work_id = ANY(:ids)"),
                {"ids": [w for w, _, _ in found]},
            )
            refresh_availability_view(conn)
            version = bump_catalog_version(conn)
            print(f"\nremoved {len(found)} books; catalog_version={version}")


if __name__ == "__main__":
    main()
