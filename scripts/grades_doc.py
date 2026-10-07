"""Review suggested grades as one Markdown document instead of screen by screen.

    uv run python scripts/grades_doc.py export                # writes eval/grades_review.md
    uv run python scripts/grades_doc.py import --judge NF     # reads your edits back

The document has one section per query, books sorted by suggested grade (relevant first), each
with title, author, year, pages, genres, a short blurb and the reason for the grade. To correct a
grade, change the number in its Grade cell; leave everything else as it is. `import` saves every
row of the document as your reviewed grade (judge "<initials>-review") and lists what you changed.
Pairs you graded yourself are shown for reference and never overwritten.
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.judgments import (
    key_aliases,
    load_judgments,
    load_prelabels,
    save_judgments,
    set_grade,
    work_keys,
)
from shelfwise.evaluation.queries import load_queries

QUERIES = Path("eval/data/queries.csv")
QRELS = Path("eval/data/qrels.csv")
PRELABELS = Path("eval/data/prelabels.csv")
DOC = Path("eval/grades_review.md")
CATEGORY_ORDER = ("vague", "discovery", "negation", "similarity", "multi_constraint", "learning",
                  "genre", "availability", "adversarial", "lookup", "author")  # fmt: skip
BLURB_CHARS = 110
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_ROW = re.compile(r"^\|\s*([0-3])\s*\|.*\|\s*(\S+)\s*\|\s*$")
_SECTION = re.compile(r"^## (\S+) · ")

_BOOK_SQL = text(
    """
    SELECT w.work_id, w.title, w.first_pub_year, w.genres, w.description,
           (SELECT string_agg(a.display, ', ' ORDER BY wa.position) FROM work_author wa
              JOIN author a USING (author_id) WHERE wa.work_id = w.work_id) AS authors,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages
    FROM work w
    """
)

HEADER = """# Relevance grades for review

Every book the search systems returned for each test query, with the grade Claude suggested by
[GRADING.md](GRADING.md): **3** exactly right · **2** fits with a small mismatch · **1** partly
related · **0** not what they asked for. Books are sorted by grade within each query, so the
relevant ones come first.

**How to review:** read each query's table. Where you disagree, change the number in the
**Grade** column (0 to 3) and nothing else. Rows marked *(you)* are your own grades, shown for
reference. When done, run:

```bash
uv run python scripts/grades_doc.py import --judge NF
```

Every row is then saved as your reviewed grade, and the command lists what you changed. Queries
are ordered hardest first (vague, discovery, negation, similarity ...); author and lookup queries
at the end are near-mechanical.

"""


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def export(doc: Path, qrels: Path) -> None:
    queries = {q.id: q for q in load_queries(QUERIES)}
    judgments = load_judgments(qrels)
    with make_engine().connect() as conn:
        key_of = work_keys(conn)
        aliases = key_aliases(conn)
        books = {key_of[r.work_id]: r for r in conn.execute(_BOOK_SQL)}

    def current(key: str) -> str:
        return aliases.get(key, key)

    suggested = {(p.query_id, current(p.work_key)): p for p in load_prelabels(PRELABELS)}
    by_query: dict[str, dict[str, tuple[int, str, bool]]] = {}
    for j in judgments:
        key = current(j.work_key)
        if key not in books:
            continue  # removed from the catalog
        suggestion = suggested.get((j.query_id, key))
        if j.grade is not None and not j.judge.endswith("-review"):
            reason = f"Claude: {suggestion.grade}" if suggestion else ""
            by_query.setdefault(j.query_id, {})[key] = (j.grade, reason, True)
        elif suggestion:
            grade = j.grade if j.grade is not None else suggestion.grade
            by_query.setdefault(j.query_id, {})[key] = (grade, suggestion.reason, False)

    order = sorted(by_query, key=lambda q: (CATEGORY_ORDER.index(queries[q].category), q))
    lines = [HEADER, "## Contents\n"]
    lines += [
        f"- [{qid} · {queries[qid].category}: {_cell(queries[qid].text)}](#{qid.lower()})"
        for qid in order
    ]
    for qid in order:
        q, rows = queries[qid], by_query[qid]
        counts = Counter(g for g, _, _ in rows.values())
        summary = " · ".join(f"{counts[g]} at {g}" for g in (3, 2, 1, 0) if counts[g])
        lines += [
            "",
            f'<a id="{qid.lower()}"></a>',
            "",
            f"## {qid} · {q.category}",
            "",
            f"> **{_cell(q.text)}**  ",
            f"> Tests: {_cell(q.notes) or '—'} · {len(rows)} books: {summary}",
            "",
            "| Grade | Book | Why | ISBN |",
            "| --- | --- | --- | --- |",
        ]
        ranked = sorted(
            rows.items(), key=lambda kv: (-kv[1][0], books[kv[0]].title if kv[0] in books else "")
        )
        for key, (grade, reason, mine) in ranked:
            b = books.get(key)
            if b is None:
                about = "(no longer in the catalog)"
            else:
                blurb = " ".join((b.description or "").split())[:BLURB_CHARS]
                about = (f"**{_cell(b.title)}** — {_cell(b.authors or '?')} "
                         f"({b.first_pub_year or '?'}, {b.pages or '?'} pp) · {', '.join(b.genres[:3])}"
                         + (f"<br>{_cell(blurb)}…" if blurb else ""))  # fmt: skip
            grade_cell = f"{grade} *(you)*" if mine else str(grade)
            lines.append(f"| {grade_cell} | {about} | {_cell(reason)} | {key} |")
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = sum(map(len, by_query.values()))
    print(f"wrote {doc}: {len(order)} queries, {total} books")


def import_doc(doc: Path, judge: str, qrels: Path) -> None:
    judgments = load_judgments(qrels)
    with make_engine().connect() as conn:
        aliases = key_aliases(conn)

    def current(key: str) -> str:
        return aliases.get(key, key)

    suggested = {(p.query_id, current(p.work_key)): p.grade for p in load_prelabels(PRELABELS)}
    index = {(j.query_id, current(j.work_key)): i for i, j in enumerate(judgments)}
    query, saved, changed, problems = None, 0, [], []
    for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
        if match := _SECTION.match(line):
            query = match.group(1)
            continue
        if not line.startswith("| ") or line.startswith(("| Grade", "| ---")) or "*(you)*" in line:
            continue
        match = _ROW.match(line)
        if query is None or match is None:
            problems.append(f"line {number}: grade must be 0, 1, 2 or 3")
            continue
        grade, key = int(match.group(1)), current(match.group(2))
        i = index.get((query, key))
        if i is None:
            problems.append(f"line {number}: {query}/{key} is not in the pool any more")
            continue
        if judgments[i].grade is not None and not judgments[i].judge.endswith("-review"):
            continue  # an independent human grade: never overwritten
        if grade != suggested.get((query, key)):
            title = _CELL_SPLIT.split(line)[2].split("**")[1] if "**" in line else key
            changed.append(f"{query} {title}: {suggested.get((query, key))} -> {grade}")
        judgments = set_grade(judgments, i, grade, f"{judge}-review")
        saved += 1
    if problems:
        raise SystemExit(
            "Nothing saved; fix these in the document first:\n  " + "\n  ".join(problems)
        )
    save_judgments(qrels, judgments)
    print(f"saved {saved} reviewed grades to {qrels}; you changed {len(changed)}:")
    for c in changed:
        print(f"  {c}")
    left = sum(j.grade is None for j in judgments)
    print(f"{left} pairs still ungraded" + (" (re-run export to see them)" if left else ""))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("--judge", help="your initials (import)")
    parser.add_argument("--doc", type=Path, default=DOC)
    parser.add_argument("--qrels", type=Path, default=QRELS)
    args = parser.parse_args()
    if args.action == "export":
        export(args.doc, args.qrels)
    elif not args.judge:
        parser.error("import needs --judge <your initials>")
    else:
        import_doc(args.doc, args.judge, args.qrels)


if __name__ == "__main__":
    main()
