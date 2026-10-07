"""Review suggested book tags as one Markdown document instead of book by book.

    uv run python scripts/tags_doc.py export                # writes eval/tags_review.md
    uv run python scripts/tags_doc.py import --judge NF     # reads your edits back

One section per book (the same 200 books, in the same order, as `make label-tags`): the record,
a note where a tag needed judgement, and a table of suggested tags. To correct a tag, change its
Value cell; `?` means can't tell, `-` means the tag doesn't apply. `import` saves every book as
your reviewed label (judge "<initials>-review") and lists what you changed. Books you labelled
from scratch with `make label-tags` are left out of the document and never overwritten.
"""

import argparse
from pathlib import Path

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.book_card import BOOK_SQL
from shelfwise.evaluation.judgments import key_aliases, work_keys
from shelfwise.tagging.labels import FacetLabel, load_labels, save_labels, upsert_label
from shelfwise.tagging.review import load_prelabels, parse_doc, render_doc

LABELS = Path("eval/data/facet_labels.csv")
PRELABELS = Path("eval/data/facet_prelabels.csv")
DOC = Path("eval/tags_review.md")

HEADER = """# Book tags for review

Claude's suggested tags for the 200-book labelling sample, made from each book's record (and
general knowledge of well-known books) by the rules in [TAGGING.md](TAGGING.md), without looking
at the LLM tagger's output. The LLM tagger is scored against these once you've reviewed them.

**How to review:** for each book, read the record and the table. Where you disagree, change the
**Value** cell and nothing else. `?` = can't tell (left out of scoring, better than a guess),
`-` = doesn't apply (historical setting is for fiction, reading level for nonfiction; if you
change fiction, fill in the other one). A *Note* marks a call that needed judgement. When done:

```bash
make import-tags JUDGE=NF
```

Every book is then saved as your reviewed label, and the command lists what you changed.
"""


def _independent(rows: list[FacetLabel]) -> set[str]:
    return {r.work_key for r in rows if not r.judge.endswith("-review")}


def export(doc: Path) -> None:
    prelabels = load_prelabels(PRELABELS)
    own = _independent(load_labels(LABELS))
    with make_engine().connect() as conn:
        key_of = work_keys(conn)
        aliases = key_aliases(conn)
        books = {key_of[r.work_id]: r for r in conn.execute(BOOK_SQL)}
    todo = [p for p in prelabels if aliases.get(p.label.work_key, p.label.work_key) not in own]
    doc.write_text(render_doc(todo, books, HEADER), encoding="utf-8")
    skipped = len(prelabels) - len(todo)
    print(
        f"wrote {doc}: {len(todo)} books"
        + (f" ({skipped} you labelled yourself)" if skipped else "")
    )


def import_doc(doc: Path, judge: str) -> None:
    try:
        reviewed = parse_doc(doc.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SystemExit(f"Nothing saved; {error}") from None
    suggested = {p.label.work_key: p.label for p in load_prelabels(PRELABELS)}
    rows = load_labels(LABELS)
    own = _independent(rows)
    changed: list[str] = []
    saved = 0
    for book in reviewed:
        if book.work_key in own:
            continue  # labelled from scratch: never overwritten
        before = suggested.get(book.work_key)
        title = before.title if before else ""
        if before is not None:
            for tag in sorted(set(before.labels) | set(book.labels)):
                old, new = before.labels.get(tag, "?"), book.labels.get(tag, "?")
                if old != new:
                    changed.append(f"{title[:40]}: {tag} {old} -> {new}")
        label = FacetLabel(
            book.work_key, f"{judge}-review", book.labels, book.setting_period, title
        )
        rows = upsert_label(rows, label)
        saved += 1
    save_labels(LABELS, rows)
    print(f"saved {saved} reviewed labels to {LABELS}; you changed {len(changed)} tags:")
    for c in changed:
        print(f"  {c}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--judge", help="your initials (import)")
    parser.add_argument("--doc", type=Path, default=DOC)
    args = parser.parse_args()
    if args.action == "export":
        export(args.doc)
    elif not args.judge:
        parser.error("import needs --judge <your initials>")
    else:
        import_doc(args.doc, args.judge)


if __name__ == "__main__":
    main()
