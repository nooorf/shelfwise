"""Measure how well Claude's grades agree with yours, on a blind sample (eval/GRADING.md).

    uv run python scripts/blind.py draw                  # Claude: writes eval/data/blind_sample.csv
    uv run python scripts/label.py --judge NF --qrels eval/data/blind_sample.csv   # you grade it
    uv run python scripts/blind.py score --judge NF      # agreement with Claude's grades

The sample file has the same columns as qrels.csv, so `label.py` grades it as usual and never shows
Claude's grade. Your grades stay in the sample file; qrels.csv is not touched.
"""

import argparse
import csv
from pathlib import Path

from shelfwise.evaluation.blind import Candidate, draw, score
from shelfwise.evaluation.judgments import (
    CLAUDE_REVIEW,
    Judgment,
    load_judgments,
    load_prelabels,
    save_judgments,
)
from shelfwise.evaluation.queries import QUERY_FILES, load_query_files

QRELS = Path("eval/data/qrels.csv")
PRELABELS = Path("eval/data/prelabels.csv")
SAMPLE = Path("eval/data/blind_sample.csv")


def _draw(per_grade: int, seed: int, exclude: Path | None) -> None:
    if any(j.grade is not None for j in load_judgments(SAMPLE)):
        raise SystemExit(f"{SAMPLE} already has grades; drawing again would discard them")
    category = {q.id: q.category for q in load_query_files(QUERY_FILES)}
    suggested = {(p.query_id, p.work_key): p.grade for p in load_prelabels(PRELABELS)}
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
    print(f"wrote {SAMPLE}: {len(rows)} pairs from {len({r.query_id for r in rows})} queries")


def _score(judge: str) -> None:
    category = {q.id: q.category for q in load_query_files(QUERY_FILES)}
    sample = load_judgments(SAMPLE)
    person = {
        (j.query_id, j.work_key): j.grade
        for j in sample
        if j.grade is not None and j.judge == judge
    }
    claude = {(p.query_id, p.work_key): p.grade for p in load_prelabels(PRELABELS)}
    if not person:
        raise SystemExit(f"no grades by {judge} in {SAMPLE} yet")
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
    parser.add_argument("action", choices=["draw", "score"])
    parser.add_argument("--judge", help="your initials (score)")
    parser.add_argument("--per-grade", type=int, default=40, help="pairs per Claude grade (draw)")
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument(
        "--exclude", type=Path, help="CSV of query_id,work_key pairs the grader has seen (draw)"
    )
    args = parser.parse_args()
    if args.action == "draw":
        _draw(args.per_grade, args.seed, args.exclude)
    elif not args.judge:
        parser.error("score needs --judge <your initials>")
    else:
        _score(args.judge)


if __name__ == "__main__":
    main()
