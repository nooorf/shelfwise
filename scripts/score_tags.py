"""Score book tags against human labels: per-tag accuracy and Cohen's kappa; saves a JSON report.

    uv run python scripts/score_tags.py                  # the LLM's tags vs the main labeller
    uv run python scripts/score_tags.py --judge XY       # vs someone else's labels
    uv run python scripts/score_tags.py --judges NF XY   # two people: the realistic ceiling
    uv run python scripts/score_tags.py --fiction-only   # novels only

A tag is only scored where it applies by the human's answer (setting for fiction, reading level for
nonfiction) and where both sides gave a value ("can't tell" is left out). "majority" is the
accuracy of always answering the human's most common value: a tagger has to beat it to be useful.
"""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from shelfwise.catalog.db import make_engine
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.tagging.labels import Labels, agreement_by_tag, llm_labels, load_labels

LABELS = Path("eval/data/facet_labels.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--judge", help="human labeller to score the LLM against (default: most labels)"
    )
    parser.add_argument("--judges", nargs=2, metavar=("A", "B"), help="compare two people instead")
    parser.add_argument(
        "--fiction-only",
        action="store_true",
        help="only books the human marked as fiction (mood tags are trivially 0 on textbooks)",
    )
    parser.add_argument("--labels", type=Path, default=LABELS)
    args = parser.parse_args()

    rows = load_labels(args.labels)
    by_judge: dict[str, dict[str, Labels]] = {}
    for r in rows:
        by_judge.setdefault(r.judge, {})[r.work_key] = r.labels
    if not by_judge:
        raise SystemExit(f"No labels in {args.labels} yet: run `make label-tags JUDGE=<initials>`.")

    report: dict = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
    }
    if args.judges:
        a, b = args.judges
        missing = [j for j in (a, b) if j not in by_judge]
        if missing:
            raise SystemExit(f"No labels by {', '.join(missing)} in {args.labels}.")
        reference, other = by_judge[a], by_judge[b]
        report["compared"] = f"{a} vs {b}"
    else:
        judge = args.judge or max(by_judge, key=lambda j: len(by_judge[j]))
        if judge not in by_judge:
            raise SystemExit(f"No labels by {judge} in {args.labels}.")
        reference = by_judge[judge]
        with make_engine().connect() as conn:
            llm = llm_labels(conn)
        other = {key: labels for key, (_, labels) in llm.items()}
        versions = Counter(llm[key][0] for key in reference if key in llm)
        report["compared"] = f"{judge} vs llm"
        report["model_versions"] = dict(versions)
        untagged = [key for key in reference if key not in llm]
        if untagged:
            print(f"note: {len(untagged)} labelled books have no LLM tags yet (run `make tag`)")
        if len(versions) > 1:
            print(f"note: mixed tagger versions {dict(versions)}; re-tag for a clean comparison")

    if args.fiction_only:
        reference = {k: v for k, v in reference.items() if v.get("fiction") == "yes"}
        report["compared"] += " (fiction only)"
    report["books"] = sum(key in other for key in reference)
    report["tags"] = agreement_by_tag(reference, other)
    out = report_path(report["git"], "tags")
    out.write_text(json.dumps(report, indent=2))

    print(f"{report['compared']}: {report['books']} books labelled by both")
    header = f"{'tag':20} {'n':>4} {'accuracy':>9} {'kappa':>7} {'±1':>6} {'majority':>9}"
    print(header)
    print("-" * len(header))
    for name, r in report["tags"].items():
        if not r["n"]:
            print(f"{name:20} {0:4}")
            continue
        kappa = "n/a" if r["kappa"] is None else f"{r['kappa']:.2f}"
        within = "" if r["within_one"] is None else f"{r['within_one']:.2f}"
        print(
            f"{name:20} {r['n']:4} {r['accuracy']:9.2f} {kappa:>7} {within:>6} {r['majority']:9.2f}"
        )
    print("\nkappa: quadratic-weighted for ordered scales (darkness, romance, violence, pace)")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
