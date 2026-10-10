"""How far one judge's negation-study tag answers can be trusted: agreement with a second judge
on the books both answered (normally the blind sample from `label_violations.py --sample-of`).

    uv run python scripts/violation_agreement.py --judges claude NF

Per tag: questions both answered, exact agreement, Cohen's kappa (quadratic on ordered scales),
and agreement on what the study counts, whether a book breaks the pair's negation. Saves
eval/reports/<time>_<git>_violation-agreement.json.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from shelfwise.evaluation.negation import load_pairs, load_violation_labels, violation_agreement
from shelfwise.evaluation.queries import QUERY_FILES, load_query_files
from shelfwise.evaluation.reports import git_version, report_path

PAIRS = Path("eval/data/negation_pairs.csv")
VIOLATION_LABELS = Path("eval/data/violation_labels.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--judges", nargs=2, required=True, metavar=("REFERENCE", "OTHER"))
    args = parser.parse_args()

    queries = {q.id: q for q in load_query_files(QUERY_FILES)}
    results = violation_agreement(
        load_violation_labels(VIOLATION_LABELS), load_pairs(PAIRS, queries), *args.judges
    )
    if not results:
        raise SystemExit(f"No questions answered by both {args.judges[0]} and {args.judges[1]}.")

    def cell(value: float | None) -> str:
        return f"{value:6.1%}" if value is not None else "   n/a"

    print(f"{'tag':13} {'n':>4} {'agree':>7} {'kappa':>6} {'same violation':>15}")
    for tag, r in results.items():
        kappa = f"{r['kappa']:6.2f}" if r["kappa"] is not None else "   n/a"
        print(f"{tag:13} {r['n']:>4} {cell(r['accuracy'])} {kappa} {cell(r['violation_agreement']):>15}")  # fmt: skip
    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "judges": args.judges,
        "by_tag": results,
    }
    out = report_path(report["git"], "violation-agreement")
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
