"""Try lexical search from the terminal.

    uv run python scripts/search.py "murder on the orient expres"
    uv run python scripts/search.py "data structures in c++" -k 5

Shows the parsed constraints, ISBN/title/author lookups, then BM25 results restricted to works
that satisfy every hard constraint (searching the query with its constraints removed). If nothing
passes the filters, shows how many works each dropped constraint would allow.
"""

import argparse
from datetime import date

from sqlalchemy import text

from shelfwise.catalog.availability import fetch_live_availability
from shelfwise.catalog.db import make_engine
from shelfwise.query.constraints import contradictions
from shelfwise.query.rules import parse_rules
from shelfwise.retrieval.filters import allowed_mask, relaxations
from shelfwise.retrieval.lexical import FIELDS, build_lexical_index
from shelfwise.retrieval.lookup import find_authors, find_by_isbn, find_titles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args()

    parse = parse_rules(args.query)
    for c in parse.constraints:
        print(f"Rule:   {c.field} {c.op} {c.value} ({c.strength})  <- {c.span!r}")
    for problem in contradictions(parse.constraints):
        print(f"Conflict: {problem.message()}")
    print(f"Residual: {parse.residual!r}\n")

    with make_engine().connect() as conn:
        titles: dict[int, str] = {
            r.work_id: r.title for r in conn.execute(text("SELECT work_id, title FROM work"))
        }
        index = build_lexical_index(conn)

        if isbn_hits := find_by_isbn(conn, args.query):
            print("ISBN:   " + "; ".join(titles[w] for w in isbn_hits))
        for m in find_titles(conn, args.query):
            print(f"Title:  {m.score:.2f}  {m.title}")
        for a in find_authors(conn, args.query):
            print(f"Author: {a.score:.2f}  {a.name} ({len(a.work_ids)} books)")

        mask = allowed_mask(conn, parse.constraints, index.work_ids)
        suggestions = relaxations(conn, parse.constraints) if not mask.any() else []
        hits = index.search(parse.residual, k=args.k, allowed=mask)
        fields = index.field_scores(parse.residual)
        row_of = {int(w): i for i, w in enumerate(index.work_ids)}
        availability = fetch_live_availability(conn, [h.work_id for h in hits])

    print(f"\nPass hard filters: {int(mask.sum())} of {len(mask)} works")
    for r in suggestions:
        print(f"  drop {r.label!r} -> {r.count} works")
    print(f"\nBM25 top {args.k}  ({' / '.join(FIELDS)})")
    for h in hits:
        per_field = " / ".join(f"{fields[f][row_of[h.work_id]]:4.1f}" for f in FIELDS)
        state = availability[h.work_id].state(date.today()).value
        print(f"  {h.score:6.2f}  [{per_field}]  {state:16} {titles[h.work_id][:60]}")
    if not hits:
        print("  (no lexical matches)")


if __name__ == "__main__":
    main()
