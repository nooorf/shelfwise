"""Grade pooled books in the terminal, one at a time. Saves after every keypress.

    uv run python scripts/label.py --judge NF          # your initials
    uv run python scripts/label.py --judge NF --query M01   # only one query

Keys: 0 1 2 3 = grade · s = skip · b = back (re-grade previous) · q = save and quit
Grading guide: eval/GRADING.md
"""

import argparse
import textwrap
from pathlib import Path

from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.judgments import load_judgments, save_judgments, set_grade, work_keys
from shelfwise.evaluation.queries import load_queries

QUERIES = Path("eval/data/queries.csv")
QRELS = Path("eval/data/qrels.csv")

_BOOK_SQL = text(
    """
    SELECT w.work_id, w.title, w.subtitle, w.first_pub_year, w.genres, w.description,
           (SELECT string_agg(a.display, ', ' ORDER BY wa.position) FROM work_author wa
              JOIN author a USING (author_id) WHERE wa.work_id = w.work_id) AS authors,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages
    FROM work w
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--judge", required=True, help="your initials, recorded with each grade")
    parser.add_argument("--query", help="only label this query id")
    parser.add_argument("--queries", type=Path, default=QUERIES)
    parser.add_argument("--qrels", type=Path, default=QRELS)
    args = parser.parse_args()

    queries = {q.id: q for q in load_queries(args.queries)}
    judgments = load_judgments(args.qrels)
    with make_engine().connect() as conn:
        key_of = work_keys(conn)
        books = {key_of[r.work_id]: r for r in conn.execute(_BOOK_SQL)}

    todo = [
        i
        for i, j in enumerate(judgments)
        if j.grade is None and (args.query is None or j.query_id == args.query)
    ]
    print(f"{len(todo)} to label. Keys: 0-3 grade, s skip, b back, q quit.\n")
    history: list[int] = []
    position = 0
    while position < len(todo):
        i = todo[position]
        j = judgments[i]
        q = queries.get(j.query_id)
        book = books.get(j.work_key)
        print("=" * 78)
        print(
            f"[{position + 1}/{len(todo)}]  {j.query_id} ({q.category if q else '?'}):  {q.text if q else '?'}"
        )
        if q and q.notes:
            print(f"   note: {q.notes}")
        print("-" * 78)
        if book is None:
            print(f"   (book {j.work_key} is no longer in the catalog: {j.title})")
        else:
            title = book.title + (f": {book.subtitle}" if book.subtitle else "")
            print(f"   {title}")
            print(f"   {book.authors or 'unknown author'} · {book.first_pub_year or '?'} · "
                  f"{book.pages or '?'} pages · {', '.join(book.genres) or 'no genres'}")  # fmt: skip
            description = (book.description or "(no description)")[:700]
            print(textwrap.indent(textwrap.fill(description, 74), "   "))
        key = input("\ngrade 0-3 / s / b / q > ").strip().lower()
        if key == "q":
            break
        if key == "b" and history:
            position = history.pop()
            judgments = set_grade(judgments, todo[position], None, args.judge)
            save_judgments(args.qrels, judgments)
            continue
        if key == "s":
            position += 1
            continue
        if key in {"0", "1", "2", "3"}:
            judgments = set_grade(judgments, i, int(key), args.judge)
            save_judgments(args.qrels, judgments)
            history.append(position)
            position += 1
        else:
            print("  -> use 0, 1, 2, 3, s, b or q")

    left = sum(j.grade is None for j in judgments)
    print(f"\nSaved. {left} pairs still unlabeled in {args.qrels}.")


if __name__ == "__main__":
    main()
