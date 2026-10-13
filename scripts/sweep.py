"""Tune retrieval settings on the dev split: fusion weights and rerank depth.

    uv run python scripts/sweep.py fusion                      # RRF k x list weights
    uv run python scripts/sweep.py depth --reranker minilm     # books reranked vs NDCG and latency

Dev split only: the test split stays locked until the final configuration is frozen. Every
setting is scored on the same queries, and the winner is reported with a paired bootstrap CI of
its gain over the default, so a gain inside the noise reads as one. With ~110 dev queries a grid
can overfit; the locked test run is the check. Saves eval/reports/<time>_<git>_sweep-<kind>.json.
"""

import argparse
import itertools
import json
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.evaluation.judgments import key_aliases, load_judgments, qrels_by_query, work_keys
from shelfwise.evaluation.metrics import bootstrap_ci, mean, ndcg_at_k
from shelfwise.evaluation.queries import Query, load_queries
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.evaluation.splits import split_of
from shelfwise.evaluation.systems import SYSTEMS, Fusion, SearchContext, load_context

QUERIES = Path("eval/data/queries.csv")
QRELS = Path("eval/data/qrels.csv")
K = 10


def score(
    ctx: SearchContext,
    system: str,
    queries: list[Query],
    qrels: dict[str, dict[str, int]],
    key_of: dict[int, str],
) -> tuple[list[float], float]:
    """Per-query NDCG@10 and p95 latency in ms."""
    SYSTEMS[system](ctx, queries[0].text, K)  # untimed: lazy loads
    values, took = [], []
    for q in queries:
        clock = time.perf_counter()
        found = SYSTEMS[system](ctx, q.text, K)
        took.append((time.perf_counter() - clock) * 1000)
        values.append(ndcg_at_k([key_of[w] for w in found], qrels[q.id], K))
    return values, float(np.percentile(took, 95))


def gain(values: list[float], base: list[float]) -> dict[str, float | list[float]]:
    diffs = [a - b for a, b in zip(values, base, strict=True)]
    return {"mean": mean(diffs), "ci95": list(bootstrap_ci(diffs))}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="kind", required=True)
    fusion = sub.add_parser("fusion", help="RRF k and list weights")
    fusion.add_argument("--k", type=int, nargs="+", default=[10, 30, 60, 100])
    fusion.add_argument("--semantic", type=float, nargs="+", default=[1, 1.5, 2, 3, 4],
                        help="embedding-list weight (BM25's is 1)")  # fmt: skip
    fusion.add_argument("--seed", type=float, nargs="+", default=[1, 2],
                        help='"like X" seed-list weight (parsed_hybrid only)')  # fmt: skip
    fusion.add_argument("--systems", nargs="+", default=["hybrid_lookup", "parsed_hybrid"])
    depth = sub.add_parser("depth", help="rerank depth: NDCG@10 against p95 latency")
    depth.add_argument("--reranker", required=True)
    depth.add_argument("--depths", type=int, nargs="+", default=[20, 50, 100, 200])
    parser.add_argument("--embedding-model", default=get_settings().embedding_model)
    args = parser.parse_args()

    with make_engine().connect() as conn:
        aliases = key_aliases(conn)
        key_of = work_keys(conn)
        qrels = qrels_by_query(load_judgments(QRELS), aliases)
        queries = [
            q
            for q in load_queries(QUERIES)
            if split_of(q.family) == "dev" and any(g >= 2 for g in qrels.get(q.id, {}).values())
        ]
        ctx = load_context(
            conn,
            args.embedding_model,
            reranker_model=getattr(args, "reranker", None),
            parser="cascade" if args.kind == "fusion" else None,
        )
        rows = []
        if args.kind == "fusion":
            default = Fusion()
            grid = [
                Fusion(k, 1.0, semantic, seed)
                for k, semantic, seed in itertools.product(args.k, args.semantic, args.seed)
            ]
            baseline: dict[str, list[float]] = {}
            settings = [default, *[g for g in grid if g != default]]
            for i, setting in enumerate(settings, 1):
                ctx.fusion = setting
                row: dict = {"setting": asdict(setting)}
                for system in args.systems:
                    if system != "parsed_hybrid" and setting.seed != default.seed:
                        continue  # the seed weight only reaches parsed_hybrid
                    values, _ = score(ctx, system, queries, qrels, key_of)
                    baseline.setdefault(system, values)
                    row[system] = {"ndcg@10": mean(values), "per_query": values}
                rows.append(row)
                cells = "  ".join(f"{s} {row[s]['ndcg@10']:.4f}" for s in args.systems if s in row)
                print(f"  [{i}/{len(settings)}] k={setting.k:<3} sem={setting.semantic:<4} "
                      f"seed={setting.seed:<3} {cells}")  # fmt: skip
            ctx.fusion = default
            best: dict[str, dict] = {}
            for system in args.systems:
                scored = [r for r in rows if system in r]
                top = max(scored, key=lambda r: r[system]["ndcg@10"])
                best[system] = {
                    "setting": top["setting"],
                    "ndcg@10": top[system]["ndcg@10"],
                    "default_ndcg@10": scored[0][system]["ndcg@10"],
                    "gain_over_default": gain(top[system]["per_query"], baseline[system]),
                }
        else:
            baseline_values: list[float] = []
            for depth_n in args.depths:
                assert ctx.reranker is not None
                ctx.reranker.clear()  # each depth pays for its own scoring
                ctx = replace(ctx, rerank_depth=depth_n)
                values, p95 = score(ctx, "hybrid_rerank", queries, qrels, key_of)
                baseline_values = baseline_values or values
                rows.append({"depth": depth_n, "ndcg@10": mean(values), "p95_ms": p95,
                             "per_query": values})  # fmt: skip
                print(f"  depth {depth_n:<4} NDCG@10 {mean(values):.4f}  p95 {p95:7.0f} ms")
            top = max(rows, key=lambda r: r["ndcg@10"])
            best = {
                "hybrid_rerank": {
                    "depth": top["depth"],
                    "ndcg@10": top["ndcg@10"],
                    "p95_ms": top["p95_ms"],
                    "gain_over_smallest": gain(top["per_query"], baseline_values),
                }
            }

    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "kind": args.kind,
        "split": "dev",
        "queries_scored": len(queries),
        "embedding_model": args.embedding_model,
        "reranker": getattr(args, "reranker", None),
        "best": best,
        "rows": rows,
    }
    out = report_path(report["git"], f"sweep-{args.kind}")
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\n{len(queries)} dev queries. Best:")
    for system, b in best.items():
        g = b["gain_over_default"] if "gain_over_default" in b else b["gain_over_smallest"]
        lo, hi = g["ci95"]
        where = b["setting"] if "setting" in b else {"depth": b["depth"]}
        print(f"  {system}: {json.dumps(where)} NDCG@10 {b['ndcg@10']:.4f}, "
              f"gain {g['mean']:+.4f} [95% CI {lo:+.4f}, {hi:+.4f}]")  # fmt: skip
    print(f"report: {out}")


if __name__ == "__main__":
    main()
