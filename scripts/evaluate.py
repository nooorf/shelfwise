"""Score retrieval systems against the graded judgments; print a table and save a JSON report.

    uv run python scripts/evaluate.py                       # dev split, all systems
    uv run python scripts/evaluate.py --systems bm25 bm25_lookup
    uv run python scripts/evaluate.py --split test          # the locked test split: milestones only

Queries with no relevant book (grade >= 2) are left out of the averages and listed separately;
for those the right behaviour is an honest "no match", which is tested elsewhere.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from shelfwise.catalog.db import make_engine
from shelfwise.catalog.meta import get_catalog_version
from shelfwise.config import get_settings
from shelfwise.evaluation.judgments import load_judgments, qrels_by_query, work_keys
from shelfwise.evaluation.metrics import bootstrap_ci, mean, query_metrics
from shelfwise.evaluation.queries import load_queries
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.evaluation.splits import split_of
from shelfwise.evaluation.systems import SYSTEMS, available_systems, load_context

QUERIES = Path("eval/data/queries.csv")
QRELS = Path("eval/data/qrels.csv")
K = 10


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--systems", nargs="+", default=list(SYSTEMS), choices=list(SYSTEMS))
    parser.add_argument("--queries", type=Path, default=QUERIES)
    parser.add_argument("--embedding-model", default=get_settings().embedding_model)
    parser.add_argument("--qrels", type=Path, default=QRELS)
    args = parser.parse_args()

    queries = [
        q
        for q in load_queries(args.queries)
        if args.split == "all" or split_of(q.family) == args.split
    ]
    qrels = qrels_by_query(load_judgments(args.qrels))
    scored = [q for q in queries if any(g >= 2 for g in qrels.get(q.id, {}).values())]
    no_relevant = [q.id for q in queries if q not in scored]
    if not scored:
        raise SystemExit("No graded queries with a relevant book yet: run pool.py, then label.py.")

    report: dict = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "split": args.split,
        "k": K,
        "queries_scored": len(scored),
        "queries_without_relevant": no_relevant,
        "systems": {},
    }
    with make_engine().connect() as conn:
        report["catalog_version"] = get_catalog_version(conn)
        report["embedding_model"] = args.embedding_model
        ctx = load_context(conn, args.embedding_model)
        key_of = work_keys(conn)
        for name in available_systems(ctx, args.systems):
            per_query = {}
            for q in scored:
                ranked = [key_of[w] for w in SYSTEMS[name](ctx, q.text, K)]
                per_query[q.id] = {"category": q.category, **query_metrics(ranked, qrels[q.id], K)}
            metrics = [m for m in next(iter(per_query.values())) if m != "category"]
            overall = {}
            for m in metrics:
                values = [pq[m] for pq in per_query.values()]
                overall[m] = {"mean": mean(values), "ci95": bootstrap_ci(values)}
            by_category: dict[str, list[float]] = defaultdict(list)
            for pq in per_query.values():
                by_category[pq["category"]].append(pq[f"ndcg@{K}"])
            report["systems"][name] = {
                "overall": overall,
                f"ndcg@{K}_by_category": {c: mean(v) for c, v in sorted(by_category.items())},
                "per_query": per_query,
            }

    out = report_path(report["git"], args.split)
    out.write_text(json.dumps(report, indent=2))

    print(
        f"{args.split} split: {len(scored)} queries scored ({len(no_relevant)} without a relevant book)"
    )
    header = (
        f"{'system':14} {'NDCG@10':>18} {'Recall@10':>10} {'MRR':>6} {'Hit@10':>7} {'judged@10':>9}"
    )
    print(header)
    print("-" * len(header))
    for name, result in report["systems"].items():
        o = result["overall"]
        low, high = o[f"ndcg@{K}"]["ci95"]
        print(
            f"{name:14} {o[f'ndcg@{K}']['mean']:.3f} [{low:.2f}-{high:.2f}] "
            f"{o[f'recall@{K}']['mean']:10.3f} {o['mrr']['mean']:6.3f} {o[f'hit@{K}']['mean']:7.3f} "
            f"{o[f'judged@{K}']['mean']:9.2f}"
        )
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
