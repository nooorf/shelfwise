"""Hand-label book tags in the terminal: the answers the LLM tagger is scored against.

    uv run python scripts/label_tags.py --judge NF               # until 200 books are labelled
    uv run python scripts/label_tags.py --judge XY --target 50   # a second person's overlap set

Books come in a fixed, genre-balanced order, so two people labelling "the first 50" see the same
books. The LLM's tags are never shown: judge from the record and what you know of the book.
Saves after every book. Rules: eval/TAGGING.md

At each question: the option key · ? can't tell · b back · s skip book · q quit
"""

import argparse
import textwrap
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Row, text

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.judgments import work_keys
from shelfwise.tagging.labels import (
    FACETS,
    FacetLabel,
    FacetSpec,
    labelling_order,
    load_labels,
    save_labels,
    upsert_label,
)

LABELS = Path("eval/data/facet_labels.csv")
MAX_SUBJECTS = 15
MAX_DESCRIPTION = 1200

_BOOK_SQL = text(
    """
    SELECT w.work_id, w.title, w.subtitle, w.first_pub_year, w.genres, w.tags, w.description,
           (SELECT string_agg(a.display, ', ' ORDER BY wa.position) FROM work_author wa
              JOIN author a USING (author_id) WHERE wa.work_id = w.work_id) AS authors,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages
    FROM work w
    """
)


def show(book: Row[Any], position: int, total: int) -> None:
    title = book.title + (f": {book.subtitle}" if book.subtitle else "")
    print("\n" + "=" * 78)
    print(f"[{position}/{total}]  {title}")
    print(f"   {book.authors or 'unknown author'} · {book.first_pub_year or '?'} · "
          f"{book.pages or '?'} pages · {', '.join(book.genres) or 'no genres'}")  # fmt: skip
    if book.tags:
        subjects = "subjects: " + ", ".join(book.tags[:MAX_SUBJECTS])
        print(textwrap.fill(subjects, 77, initial_indent="   ", subsequent_indent="   "))
    print("-" * 78)
    description = (book.description or "(no description)")[:MAX_DESCRIPTION]
    print(textwrap.indent(textwrap.fill(description, 74), "   "))
    print("-" * 78)


def prompt(spec: FacetSpec) -> str:
    options = " · ".join(f"{key} {shown}" for key, _, shown in spec.options)
    return f"{spec.question}  {options} · ? can't tell\n> "


def ask() -> tuple[dict[str, str], str] | Literal["skip", "quit"]:
    """Ask every tag that applies; returns (labels, setting_period), or "skip" / "quit"."""
    answers: dict[str, str | None] = {}
    history: list[int] = []
    i = 0
    while i < len(FACETS):
        spec = FACETS[i]
        known = {k: v for k, v in answers.items() if v}
        if not spec.applies(known):
            answers.pop(spec.name, None)
            i += 1
            continue
        key = input(prompt(spec)).strip().lower()
        if key == "q":
            return "quit"
        if key == "s":
            return "skip"
        if key == "b":
            if history:
                i = history.pop()
            else:
                print("  (this is the first question)")
            continue
        if key == "?":
            answers[spec.name] = None
        elif (value := spec.parse(key)) is not None:
            answers[spec.name] = value
        else:
            print(f"  -> type one of {', '.join(k for k, _, _ in spec.options)}, ?, b, s or q")
            continue
        history.append(i)
        i += 1
    period = ""
    if answers.get("historical_setting") == "yes":
        period = input("Which period? e.g. 'Victorian London' (Enter to leave blank)\n> ").strip()
    return {k: v for k, v in answers.items() if v}, period


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--judge", required=True, help="your initials, recorded with each label")
    parser.add_argument("--target", type=int, default=200, help="stop once this many are labelled")
    parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args()

    rows = load_labels(args.labels)
    with make_engine().connect() as conn:
        key_of = work_keys(conn)
        books = {key_of[r.work_id]: r for r in conn.execute(_BOOK_SQL)}
    order = labelling_order({key: (b.genres or ["none"])[0] for key, b in books.items()})
    done = {r.work_key for r in rows if r.judge == args.judge}
    todo = [key for key in order[: args.target] if key not in done]
    print(f"{len(done)} labelled by {args.judge}, {len(todo)} to go (target {args.target}).")
    print("Keys: option letter/number · ? can't tell · b back · s skip book · q quit\n")

    for position, key in enumerate(todo, start=len(done) + 1):
        book = books[key]
        while True:
            show(book, position, args.target)
            result = ask()
            if isinstance(result, str):
                break
            labels, period = result
            summary = "  ".join(f"{k}={v}" for k, v in labels.items())
            confirm = input(f"\n  {summary}\nEnter = save · r = redo this book > ").strip().lower()
            if confirm != "r":
                rows = upsert_label(rows, FacetLabel(key, args.judge, labels, period, book.title))
                save_labels(args.labels, rows)
                break
        if result == "quit":
            break

    count = sum(r.judge == args.judge for r in rows)
    print(f"\nSaved. {count} books labelled by {args.judge} in {args.labels}.")


if __name__ == "__main__":
    main()
