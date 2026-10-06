"""Build the judging pool: each system's top results for every query, merged into qrels.csv.

    uv run python scripts/pool.py                 # depth 10, all pool systems
    uv run python scripts/pool.py --depth 15

Existing rows and grades are never changed; only new (query, book) pairs are appended with a
blank grade. Re-run after adding queries or systems, then label the blanks (scripts/label.py).
"""

import argparse
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.evaluation.judgments import (
    Judgment,
    load_judgments,
    merge_pool,
    save_judgments,
    work_keys,
)
from shelfwise.evaluation.queries import load_queries
from shelfwise.evaluation.systems import POOL_SYSTEMS, SYSTEMS, available_systems, load_context

QUERIES = Path("eval/data/queries.csv")
QRELS = Path("eval/data/qrels.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--systems", nargs="+", default=list(POOL_SYSTEMS), choices=list(SYSTEMS))
    parser.add_argument("--queries", type=Path, default=QUERIES)
    parser.add_argument("--embedding-model", default=get_settings().embedding_model)
    parser.add_argument("--qrels", type=Path, default=QRELS)
    args = parser.parse_args()

    queries = load_queries(args.queries)
    existing = load_judgments(args.qrels)
    with make_engine().connect() as conn:
        ctx = load_context(conn, args.embedding_model)
        keys = work_keys(conn)
        info = {
            r.work_id: (r.title, r.author or "")
            for r in conn.execute(
                text(
                    "SELECT w.work_id, w.title, (SELECT a.display FROM work_author wa "
                    "JOIN author a USING (author_id) WHERE wa.work_id = w.work_id "
                    "ORDER BY wa.position LIMIT 1) AS author FROM work w"
                )
            )
        }
        systems = available_systems(ctx, args.systems)
        print(f"pooling from: {', '.join(systems)}")
        pooled = []
        for q in queries:
            ids = [w for name in systems for w in SYSTEMS[name](ctx, q.text, args.depth)]
            for work_id in dict.fromkeys(ids):
                title, author = info[work_id]
                pooled.append(Judgment(q.id, keys[work_id], title=title, author=author))

    merged = merge_pool(existing, pooled)
    save_judgments(args.qrels, merged)
    added = len(merged) - len(existing)
    blanks = Counter(j.query_id for j in merged if j.grade is None)
    print(
        f"{added} new pairs pooled; {sum(blanks.values())} still to label across {len(blanks)} queries"
    )
    print(f"pool size per query: avg {len(merged) / max(len(queries), 1):.1f}")


if __name__ == "__main__":
    main()
