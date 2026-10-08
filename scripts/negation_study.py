"""Run the negation study: how often each system returns books that break "not X", and how much
negation stripping and facet filters fix it, at what cost. Prints a table, saves a JSON report.

    uv run python scripts/negation_study.py --judge NF
    uv run python scripts/negation_study.py --judge NF --reranker minilm   # adds hybrid_rerank

Needs: the pairs pooled and graded (make pool, review), the books' tag questions answered
(make label-violations), and the LLM tags in the database (make tag). Design: docs, §40.1 B.
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from shelfwise.catalog.db import make_engine
from shelfwise.catalog.meta import get_catalog_version
from shelfwise.config import get_settings
from shelfwise.evaluation.judgments import key_aliases, load_judgments, qrels_by_query, work_keys
from shelfwise.evaluation.negation import human_tags, load_pairs, load_violation_labels
from shelfwise.evaluation.negation_study import (
    SOFT_PENALTY,
    Condition,
    FacetMode,
    QueryText,
    facet_filter,
    run_study,
)
from shelfwise.evaluation.queries import QUERY_FILES, load_query_files
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.evaluation.systems import SYSTEMS, available_systems, load_context
from shelfwise.query.constraints import Constraint
from shelfwise.retrieval.filters import allowed_work_ids
from shelfwise.tagging.labels import load_labels

PAIRS = Path("eval/data/negation_pairs.csv")
QRELS = Path("eval/data/qrels.csv")
FACET_LABELS = Path("eval/data/facet_labels.csv")
VIOLATION_LABELS = Path("eval/data/violation_labels.csv")
STUDY_SYSTEMS = ("bm25", "dense", "hybrid", "hybrid_rerank")


def _pct(stat: dict) -> str:
    if stat["mean"] is None:
        return f"{'n/a':>17}"
    low, high = stat["ci95"]
    return f"{stat['mean']:6.1%} [{low:4.0%}-{high:4.0%}]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--judge", required=True, help="whose tag answers decide violations")
    parser.add_argument("--systems", nargs="+", default=list(STUDY_SYSTEMS), choices=list(SYSTEMS))
    parser.add_argument("--embedding-model", default=get_settings().embedding_model)
    parser.add_argument("--reranker", help="cross-encoder for hybrid_rerank, e.g. minilm")
    args = parser.parse_args()

    queries = {q.id: q for q in load_query_files(QUERY_FILES)}
    pairs = load_pairs(PAIRS, queries)
    with make_engine().connect() as conn:
        ctx = load_context(conn, args.embedding_model, reranker_model=args.reranker)
        systems = available_systems(ctx, args.systems)
        key_of = work_keys(conn)
        aliases = key_aliases(conn)
        everything = set(key_of)
        tagged_violators = {
            p.pair: everything - allowed_work_ids(conn, [facet_filter(p.violation)]) for p in pairs
        }
        tags = human_tags(
            load_violation_labels(VIOLATION_LABELS), load_labels(FACET_LABELS), args.judge, aliases
        )
        qrels = qrels_by_query(load_judgments(QRELS), aliases)

        def rank(system: str, text: str, extra: Sequence[Constraint], k: int) -> list[int]:
            return SYSTEMS[system](replace(ctx, extra_constraints=tuple(extra)), text, k)

        conditions = [
            Condition(s, t, f)
            for s in systems
            for t in get_args(QueryText)
            for f in get_args(FacetMode)
        ]
        result = run_study(pairs, queries, conditions, rank, key_of, tagged_violators, tags, qrels)
        catalog_version = get_catalog_version(conn)

    remove = {p.pair for p in pairs if p.kind == "remove"}
    lure = {p.pair for p in pairs if p.kind == "lure"}
    cost = result.recall_cost.values()
    relevant = sum(c["relevant"] for c in cost)
    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "catalog_version": catalog_version,
        "embedding_model": args.embedding_model,
        "reranker": args.reranker,
        "judge": args.judge,
        "pairs": len(pairs),
        "soft_penalty": SOFT_PENALTY,
        "conditions": {str(c): cell.summary(remove) for c, cell in result.cells.items()},
        "base_rate": {s: cell.summary(remove) for s, cell in result.base_rate.items()},
        "lure": {
            "pairs": sorted(lure),
            "conditions": {str(c): cell.summary(lure) for c, cell in result.cells.items()},
            "base_rate": {s: cell.summary(lure) for s, cell in result.base_rate.items()},
        },
        "recall_cost": {
            "relevant": relevant,
            "removed": sum(c["removed"] for c in cost),
            "wrongly_removed": sum(c["wrongly_removed"] for c in cost),
            "per_pair": result.recall_cost,
        },
        "per_pair": {
            str(c): {p: cell.ranked[p] for p in cell.ranked} for c, cell in result.cells.items()
        },
    }
    out = report_path(report["git"], "negation-study")
    out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"negation study: {len(remove)} remove pairs (table) + {len(lure)} lure pairs (JSON), "
          f"violations judged by {args.judge}")  # fmt: skip
    header = (
        f"{'condition':30} {'violation@10':>18} {'violation@5':>18} {'NDCG@10':>18} {'lab@10':>6}"
    )
    print(header)
    print("-" * len(header))
    for system, cell in result.base_rate.items():
        s = cell.summary(remove)
        print(f"{system + '/base query':30} {_pct(s['violation@10'])} {_pct(s['violation@5'])} "
              f"{'':>18} {s['labelled@10']:6.1f}")  # fmt: skip
    for condition, cell in result.cells.items():
        s = cell.summary(remove)
        print(f"{condition!s:30} {_pct(s['violation@10'])} {_pct(s['violation@5'])} "
              f"{_pct(s['ndcg@10'])} {s['labelled@10']:6.1f}")  # fmt: skip
    if not tags:
        print(f"\nnote: no tag answers by {args.judge} yet: run make label-violations first")
    if not any(q in qrels for p in pairs for q in (p.base, p.negated)):
        print("note: the pairs aren't graded yet: run make pool, then review the grades")
    removed = report["recall_cost"]["removed"]
    wrongly = report["recall_cost"]["wrongly_removed"]
    if relevant:
        print(f"\nhard filter: removes {removed} of {relevant} relevant books ({removed / relevant:.1%}); "
              f"{wrongly} of them don't actually violate (tagger mistakes)")  # fmt: skip
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
