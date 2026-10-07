"""Decide which near-duplicate works are really one book; approved pairs are merged.

    uv run python scripts/review_duplicates.py

Shows each undecided pair (similar titles, same first author) side by side. Every decision is
saved to data/seed/work_merges.csv, so a pair is only ever asked once and merges are replayed on
every import. Approved merges are applied when you finish; then run `make embed`.

Keys: 1 = same book, keep the first record · 2 = same book, keep the second · k = different books
      s = skip for now · q = save and quit
"""

import argparse
import textwrap
from pathlib import Path

from sqlalchemy import Connection, text

from shelfwise.catalog.db import make_engine
from shelfwise.ingest.merges import (
    MERGES,
    MergeDecision,
    apply_merges,
    find_candidates,
    load_decisions,
    save_decisions,
)

_WORK_SQL = text(
    """
    SELECT w.title, w.subtitle, w.first_pub_year, w.description,
           (SELECT string_agg(a.display, ', ' ORDER BY wa.position) FROM work_author wa
              JOIN author a USING (author_id) WHERE wa.work_id = w.work_id) AS authors,
           (SELECT string_agg(coalesce(e.publisher, '?') || ' ' || coalesce(e.pub_year::text, '?')
                              || ', ' || coalesce(e.pages::text, '?') || ' pp', '; ')
              FROM edition e WHERE e.work_id = w.work_id) AS editions
    FROM work w WHERE w.work_id = :id
    """
)


def show(conn: Connection, label: str, work_id: int, isbn: str) -> None:
    w = conn.execute(_WORK_SQL, {"id": work_id}).one()
    title = w.title + (f": {w.subtitle}" if w.subtitle else "")
    print(f" {label}  {title}")
    print(f"    {w.authors} · first published {w.first_pub_year or '?'} · ISBN {isbn}")
    print(textwrap.fill(f"editions: {w.editions or 'none'}", 76, initial_indent="    ",
                        subsequent_indent="    "))  # fmt: skip
    description = (w.description or "(no description)")[:300]
    print(textwrap.indent(textwrap.fill(description, 72), "    "))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--merges", type=Path, default=MERGES)
    args = parser.parse_args()

    decisions = load_decisions(args.merges)
    engine = make_engine()
    with engine.connect() as conn:
        candidates = find_candidates(conn, decisions)
        print(f"{len(candidates)} pairs to review.")
        for n, c in enumerate(candidates, start=1):
            print("\n" + "=" * 78)
            print(f"[{n}/{len(candidates)}]  same book? (title similarity {c.score:.0f}/100)\n")
            show(conn, "1", c.work_a, c.isbn_a)
            print()
            show(conn, "2", c.work_b, c.isbn_b)
            while (key := input("\n1 / 2 = same book, keep that record · k = different books · "
                                "s skip · q quit > ").strip().lower()) not in {"1", "2", "k", "s", "q"}:  # fmt: skip
                print("  -> use 1, 2, k, s or q")
            if key == "q":
                break
            if key == "s":
                continue
            first, second = (c.isbn_a, c.title_a), (c.isbn_b, c.title_b)
            keep, other = (second, first) if key == "2" else (first, second)
            decision = "separate" if key == "k" else "merge"
            decisions.append(MergeDecision(keep[0], other[0], decision, keep[1], other[1]))
            save_decisions(args.merges, decisions)

    with engine.begin() as conn:
        merged = apply_merges(conn, decisions)
    print(f"\nSaved to {args.merges}. Merged {merged} works.")
    if merged:
        print("next: `make embed` (merged books have new search text)")


if __name__ == "__main__":
    main()
