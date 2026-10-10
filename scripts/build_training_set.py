"""Build the fine-tuning data from the graded dev queries and the synthetic requests.

    uv run python scripts/build_training_set.py                    # everything
    uv run python scripts/build_training_set.py --subset 0.05      # small set for debugging on the Mac

Writes data/processed/training/:
  embedder_train.jsonl   (anchor, positive, negative) triplets
  reranker_train.jsonl   (query, document, label) pairs, label = grade / 3 or 1/0
  val.json               the val fold: queries, relevant books, base-model candidates
  corpus.json            work_key -> search text, for the val evaluators
  manifest.json          counts and the versions everything came from

Only dev-split query families are read; their val fold is kept out of training (data.py). The
negatives for synthetic requests come from the base embedder, so run `make embed` first.
"""

import argparse
import json
import random
import subprocess
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np
from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.embed.encoder import load_embedder
from shelfwise.embed.models import MODELS
from shelfwise.evaluation.judgments import key_aliases, load_judgments, work_keys
from shelfwise.evaluation.queries import QUERY_FILES, load_query_files
from shelfwise.retrieval.dense import DenseIndex
from shelfwise.training.data import (
    RELEVANT,
    dev_queries,
    graded_examples,
    load_synthetic,
    mine_negatives,
    synthetic_examples,
    write_jsonl,
)
from shelfwise.training.synthetic import PROMPT_VERSION

QRELS = Path("eval/data/qrels.csv")
SYNTHETIC = Path("data/training/synthetic_requests.jsonl")
OUT = Path("data/processed/training")
DEPTH = 60  # base-model ranking depth that negatives are mined from
CANDIDATES = 30  # books per val query the reranker evaluator reorders


def rank(
    index: DenseIndex, vectors: np.ndarray, key_of_row: list[str], depth: int
) -> list[list[str]]:
    scores = vectors @ index.matrix.T  # (queries, books)
    top = np.argsort(-scores, axis=1)[:, :depth]
    return [[key_of_row[i] for i in row] for row in top]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--embedding-model", default=get_settings().embedding_model)
    parser.add_argument("--subset", type=float, default=1.0, help="fraction of synthetic requests")
    parser.add_argument("--graded-repeat", type=int, default=2,
                        help="times each graded example appears (they are few but real)")  # fmt: skip
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--synthetic", type=Path, default=SYNTHETIC)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    queries = load_query_files(QUERY_FILES)
    with make_engine().connect() as conn:
        keys = work_keys(conn)
        aliases = key_aliases(conn)
        texts: dict[str, str] = {}
        authors: dict[str, frozenset[int]] = {}
        for r in conn.execute(
            text(
                "SELECT w.work_id, w.search_text, coalesce((SELECT array_agg(wa.author_id) "
                "FROM work_author wa WHERE wa.work_id = w.work_id), '{}') AS author_ids "
                "FROM work w WHERE w.search_text IS NOT NULL"
            )
        ):
            texts[keys[r.work_id]] = r.search_text
            authors[keys[r.work_id]] = frozenset(r.author_ids)
        work_ids = np.array(sorted(keys), dtype=np.int64)
        index = DenseIndex.load(conn, args.embedding_model, work_ids)
    key_of_row = [keys[int(w)] for w in work_ids]
    judgments = [
        replace(j, work_key=aliases.get(j.work_key, j.work_key)) for j in load_judgments(QRELS)
    ]

    rng = random.Random(args.seed)
    synthetic = [
        r
        for r in load_synthetic(args.synthetic)
        if r.prompt_version == PROMPT_VERSION and not r.rejected
    ]
    if args.subset < 1:
        synthetic = rng.sample(synthetic, int(len(synthetic) * args.subset))
    train_q, val_q = dev_queries(queries, "train"), dev_queries(queries, "val")

    embedder = load_embedder(args.embedding_model)
    prefix = MODELS[args.embedding_model].query_prefix
    print(f"mining negatives for {len(synthetic)} synthetic requests with {args.embedding_model}")
    vectors = embedder.encode_documents([prefix + r.text for r in synthetic]) if synthetic else None
    negatives = {}
    if vectors is not None:
        for r, ranked in zip(synthetic, rank(index, vectors, key_of_row, DEPTH), strict=True):
            negatives[r.text] = mine_negatives(ranked, r.work_key, authors)

    g_trip, g_pairs = graded_examples(train_q, judgments, texts, seed=args.seed)
    s_trip, s_pairs = synthetic_examples(synthetic, texts, negatives)
    triplets = g_trip * args.graded_repeat + s_trip
    pairs = g_pairs * args.graded_repeat + s_pairs
    rng.shuffle(triplets)
    rng.shuffle(pairs)

    val_vectors = embedder.encode_documents([prefix + q.text for q in val_q])
    val_ranked = rank(index, val_vectors, key_of_row, CANDIDATES)
    relevant: dict[str, list[str]] = defaultdict(list)
    for j in judgments:
        if j.grade is not None and j.grade >= RELEVANT and j.work_key in texts:
            relevant[j.query_id].append(j.work_key)
    val = {
        "queries": {q.id: q.text for q in val_q if relevant.get(q.id)},
        "relevant": {q.id: sorted(relevant[q.id]) for q in val_q if relevant.get(q.id)},
        "candidates": {
            q.id: ranked for q, ranked in zip(val_q, val_ranked, strict=True) if relevant.get(q.id)
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    counts = {
        "embedder_train": write_jsonl(args.out / "embedder_train.jsonl", triplets),
        "reranker_train": write_jsonl(args.out / "reranker_train.jsonl", pairs),
        "graded_triplets": len(g_trip),
        "graded_pairs": len(g_pairs),
        "synthetic_triplets": len(s_trip),
        "synthetic_pairs": len(s_pairs),
        "train_queries": len(train_q),
        "val_queries": len(val["queries"]),
    }
    (args.out / "val.json").write_text(json.dumps(val, indent=1))
    (args.out / "corpus.json").write_text(json.dumps(texts, ensure_ascii=False))
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    manifest = {
        **counts,
        "embedding_model": args.embedding_model,
        "synthetic_prompt": PROMPT_VERSION,
        "synthetic_models": dict(Counter(r.model for r in synthetic)),
        "subset": args.subset,
        "graded_repeat": args.graded_repeat,
        "seed": args.seed,
        "git": git.stdout.strip(),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    for name, n in counts.items():
        print(f"  {name:20} {n}")
    print(f"wrote {args.out}/")


if __name__ == "__main__":
    main()
