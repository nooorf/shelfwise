"""Measure how well Claude's grades agree with yours, on a blind sample (eval/GRADING.md).

    uv run python scripts/blind.py draw                  # Claude: writes eval/data/blind_sample.csv
    uv run python scripts/blind.py doc                   # eval/blind_review.md, grade cells empty
    uv run python scripts/blind.py import --judge NF     # your filled-in grades -> the sample file
    uv run python scripts/blind.py score --judge NF      # agreement with Claude's grades

Or grade in the terminal instead of the document:
    uv run python scripts/label.py --judge NF --qrels eval/data/blind_sample.csv

The sample file has the same columns as qrels.csv. Neither way shows Claude's grade. Your grades
stay in the sample file; qrels.csv is not touched.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.blind import Candidate, draw, parse_doc, score
from shelfwise.evaluation.judgments import (
    CLAUDE_REVIEW,
    Judgment,
    load_judgments,
    load_prelabels,
    save_judgments,
    save_prelabels,
    set_grade,
    work_keys,
)
from shelfwise.evaluation.queries import QUERY_FILES, load_query_files

QRELS = Path("eval/data/qrels.csv")
PRELABELS = Path("eval/data/prelabels.csv")
SAMPLE = Path("eval/data/blind_sample.csv")
FROZEN = Path("eval/data/blind_sample_claude.csv")  # Claude's grades when the sample was drawn
DOC = Path("eval/blind_review.md")
BLURB_CHARS = 400

_BOOK_SQL = text(
    """
    SELECT w.work_id, w.title, w.subtitle, w.first_pub_year, w.genres, w.description,
           (SELECT string_agg(a.display, ', ' ORDER BY wa.position) FROM work_author wa
              JOIN author a USING (author_id) WHERE wa.work_id = w.work_id) AS authors,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages
    FROM work w
    """
)

HEADER = """# Blind sample: your grades

{n} books, each paired with a search query. Claude has graded them too, but its grades are not
here: the point is to see how often you'd agree without seeing them. So please don't look these
books up in `grades_review.md` (it shows Claude's grade) until you're done.

**The question for every row:** would this person be happy if a librarian handed them this book?

| Grade | Meaning |
| --- | --- |
| **3** | Exactly what they asked for; you'd hand it over |
| **2** | Clearly fits, with a small mismatch |
| **1** | Partly related: right genre but wrong mood, or right topic but wrong level |
| **0** | Not what they asked for |

- **Judge from what's shown.** You don't need to have read the book.
- **Ignore exact numbers and availability** ("under 300 pages", "after 2015", "on the shelf now").
  Do judge vague wishes ("short", "dark", "cozy", "for beginners").
- **Negations** ("no romance", "nothing supernatural"): a book that clearly has what was ruled out
  is 0. A minor bit of it: at most 1.
- **"Books like X":** X itself is 0. **A book that doesn't exist:** everything is 0, except the
  real book it refers to (1).
- **House rules:** a later book in a series that tells one continuing story is at most 2 (book 1
  can be 3); picture books are 0 unless the request is for children.
- **Torn between two grades? Pick the lower one.** Can't tell from the record? Leave it empty.

**How:** type 0, 1, 2 or 3 in the empty Grade cell of each row and change nothing else. Save and
stop whenever you like. When you're done, tell Claude (it runs
`uv run python scripts/blind.py import --judge NF`).

"""


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def _doc() -> None:
    queries = {q.id: q for q in load_query_files(QUERY_FILES)}
    sample = load_judgments(SAMPLE)
    with make_engine().connect() as conn:
        key_of = work_keys(conn)
        books = {key_of[r.work_id]: r for r in conn.execute(_BOOK_SQL)}
    by_query: dict[str, list[Judgment]] = defaultdict(list)
    for j in sample:  # sections in the sample's (random) order
        by_query[j.query_id].append(j)
    lines = [HEADER.format(n=len(sample))]
    for qid, rows in by_query.items():
        q = queries[qid]
        lines += ["", f"## {qid} · {q.category}", "", f"> **{_cell(q.text)}**", "",
                  "| Grade | Book | ISBN |", "| --- | --- | --- |"]  # fmt: skip
        for j in rows:
            b = books.get(j.work_key)
            if b is None:
                about = f"**{_cell(j.title)}** — {_cell(j.author)} (no longer in the catalog)"
            else:
                title = b.title + (f": {b.subtitle}" if b.subtitle else "")
                blurb = " ".join((b.description or "").split())
                if len(blurb) > BLURB_CHARS:
                    blurb = blurb[:BLURB_CHARS].rsplit(" ", 1)[0] + "…"
                about = (f"**{_cell(title)}** — {_cell(b.authors or '?')} "
                         f"({b.first_pub_year or '?'}, {b.pages or '?'} pp) · "
                         f"{', '.join(b.genres[:4]) or 'no genres'}"
                         + (f"<br>{_cell(blurb)}" if blurb else ""))  # fmt: skip
            grade = "" if j.grade is None else str(j.grade)
            lines.append(f"| {grade} | {about} | {j.work_key} |")
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {DOC}: {len(sample)} books in {len(by_query)} queries")


def _import(judge: str) -> None:
    grades, problems = parse_doc(DOC.read_text(encoding="utf-8"))
    if problems:
        raise SystemExit(
            "Nothing saved; fix these in the document first:\n  " + "\n  ".join(problems)
        )
    sample = load_judgments(SAMPLE)
    graded = 0
    for i, j in enumerate(sample):
        grade = grades.get((j.query_id, j.work_key))
        if grade is not None:
            sample = set_grade(sample, i, grade, judge)
            graded += 1
    save_judgments(SAMPLE, sample)
    print(f"saved {graded} of {len(sample)} grades to {SAMPLE}; {len(sample) - graded} left empty")


def _draw(per_grade: int, seed: int, exclude: Path | None) -> None:
    if any(j.grade is not None for j in load_judgments(SAMPLE)):
        raise SystemExit(f"{SAMPLE} already has grades; drawing again would discard them")
    category = {q.id: q.category for q in load_query_files(QUERY_FILES)}
    prelabels = {(p.query_id, p.work_key): p for p in load_prelabels(PRELABELS)}
    suggested = {pair: p.grade for pair, p in prelabels.items()}
    shown: set[tuple[str, str]] = set()
    if exclude:
        with exclude.open(newline="", encoding="utf-8") as f:
            shown = {(r["query_id"], r["work_key"]) for r in csv.DictReader(f)}
    pool = {(j.query_id, j.work_key): j for j in load_judgments(QRELS)}
    candidates = [
        Candidate(q, k, category[q], suggested[(q, k)])
        for (q, k), j in pool.items()
        if j.judge in ("", CLAUDE_REVIEW)  # nobody has graded or reviewed it by hand
        and (q, k) in suggested
        and (q, k) not in shown
        and q in category
    ]
    sample = draw(candidates, per_grade, seed)
    rows = [
        Judgment(c.query_id, c.work_key, title=pool[(c.query_id, c.work_key)].title,
                 author=pool[(c.query_id, c.work_key)].author)
        for c in sample
    ]  # fmt: skip
    save_judgments(SAMPLE, rows)
    # Frozen, so correcting Claude's grades later (after seeing yours) can't inflate agreement.
    save_prelabels(FROZEN, [prelabels[(c.query_id, c.work_key)] for c in sample])
    print(f"wrote {SAMPLE}: {len(rows)} pairs from {len({r.query_id for r in rows})} queries")


def _score(judge: str, path: Path) -> None:
    category = {q.id: q.category for q in load_query_files(QUERY_FILES)}
    sample = load_judgments(path)
    person = {
        (j.query_id, j.work_key): j.grade
        for j in sample
        if j.grade is not None and j.judge == judge
    }
    claude = {(p.query_id, p.work_key): p.grade for p in load_prelabels(FROZEN)}
    if not person:
        raise SystemExit(f"no grades by {judge} in {path} yet")
    r = score(person, claude, category)

    def kappa(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    print(f"{r.pairs} of {len(sample)} pairs graded by {judge}\n")
    print(f"exact agreement     {r.exact:.1%}")
    print(f"within one grade    {r.within_one:.1%}")
    print(f"weighted kappa      {kappa(r.weighted_kappa)}  (quadratic, 0-3)")
    print(f"relevant/not kappa  {kappa(r.relevant_kappa)}  (2-3 vs 0-1)\n")
    print(f"{judge} \\ Claude    0    1    2    3")
    for mine in (0, 1, 2, 3):
        counts = "".join(f"{r.confusion.get((mine, c), 0):5}" for c in (0, 1, 2, 3))
        print(f"   {mine}          {counts}")
    print("\nby category (pairs, exact):")
    for cat, (n, exact) in r.by_category.items():
        print(f"  {cat:18} {n:4}  {exact:.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["draw", "doc", "import", "score"])
    parser.add_argument("--judge", help="your initials (import, score)")
    parser.add_argument("--per-grade", type=int, default=40, help="pairs per Claude grade (draw)")
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument(
        "--sample", type=Path, default=SAMPLE, help="graded sample to score, e.g. a retest (score)"
    )
    parser.add_argument(
        "--exclude", type=Path, help="CSV of query_id,work_key pairs the grader has seen (draw)"
    )
    args = parser.parse_args()
    if args.action == "draw":
        _draw(args.per_grade, args.seed, args.exclude)
    elif args.action == "doc":
        _doc()
    elif not args.judge:
        parser.error(f"{args.action} needs --judge <your initials>")
    elif args.action == "import":
        _import(args.judge)
    else:
        _score(args.judge, args.sample)


if __name__ == "__main__":
    main()
