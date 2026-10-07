"""Answer one tag question per book for the negation study: is this book supernatural, how much
romance, ... for every book pooled for a negation pair (base and negated query).

    uv run python scripts/label_violations.py --judge NF
    uv run python scripts/label_violations.py --judge NF --pair X05   # just one pair's books

The study counts a negation as violated from these answers, never from the LLM's tags (which the
facet filter under test uses). The query isn't shown either: judge the book, not the request.
Books you already labelled in full with `make label-tags` aren't asked again. Saves after every
answer. Same definitions as eval/TAGGING.md.

Keys: the option key · ? can't tell · b back one book · q quit
"""

import argparse
from pathlib import Path

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.book_card import BOOK_SQL, show
from shelfwise.evaluation.judgments import key_aliases, load_judgments, work_keys
from shelfwise.evaluation.negation import (
    ViolationLabel,
    human_tags,
    load_pairs,
    load_violation_labels,
    questions,
    save_violation_labels,
    upsert_violation_label,
)
from shelfwise.evaluation.queries import QUERY_FILES, load_query_files
from shelfwise.tagging.labels import FACET_BY_NAME, load_labels

PAIRS = Path("eval/data/negation_pairs.csv")
QRELS = Path("eval/data/qrels.csv")
FACET_LABELS = Path("eval/data/facet_labels.csv")
VIOLATION_LABELS = Path("eval/data/violation_labels.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--judge", required=True, help="your initials, recorded with each answer")
    parser.add_argument("--pair", help="only this pair's books, e.g. X05")
    parser.add_argument("--labels", type=Path, default=VIOLATION_LABELS)
    args = parser.parse_args()

    queries = {q.id: q for q in load_query_files(QUERY_FILES)}
    pairs = [p for p in load_pairs(PAIRS, queries) if not args.pair or p.pair == args.pair]
    if not pairs:
        raise SystemExit(f"No pair {args.pair!r} in {PAIRS}.")
    rows = load_violation_labels(args.labels)
    with make_engine().connect() as conn:
        key_of = work_keys(conn)
        aliases = key_aliases(conn)
        books = {key_of[r.work_id]: r for r in conn.execute(BOOK_SQL)}
    known = human_tags(rows, load_labels(FACET_LABELS), args.judge, aliases)
    todo = [
        q for q in questions(pairs, load_judgments(QRELS), known, aliases) if q.work_key in books
    ]
    if not todo:
        pooled = any(j.query_id in {p.negated for p in pairs} for j in load_judgments(QRELS))
        print(
            "Nothing to ask."
            if pooled
            else "The negation queries aren't pooled yet: run make pool."
        )
        return
    print(f"{len(todo)} questions over {len(pairs)} pairs.")
    print("Keys: option key · ? can't tell · b back one book · q quit\n")

    i = 0
    while i < len(todo):
        question = todo[i]
        spec = FACET_BY_NAME[question.facet]
        show(books[question.work_key], i + 1, len(todo))
        options = " · ".join(f"{key} {shown}" for key, _, shown in spec.options)
        key = input(f"{spec.question}  {options} · ? can't tell\n> ").strip().lower()
        if key == "q":
            break
        if key == "b":
            i = max(0, i - 1)
            continue
        value = "" if key == "?" else spec.parse(key)
        if value is None:
            print(f"  -> type one of {', '.join(k for k, _, _ in spec.options)}, ?, b or q")
            continue
        label = ViolationLabel(question.work_key, args.judge, spec.name, value, question.title)
        rows = upsert_violation_label(rows, label)
        save_violation_labels(args.labels, rows)
        i += 1

    answered = sum(r.judge == args.judge for r in rows)
    print(f"\nSaved. {answered} answers by {args.judge} in {args.labels}.")


if __name__ == "__main__":
    main()
