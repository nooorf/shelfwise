"""Fine-tune the embedding model on the training set (Phase 7).

    uv run python scripts/train_embedder.py --max-steps 30                 # smoke test on the Mac
    uv run python scripts/train_embedder.py --batch-size 64 --epochs 2     # the real run (4090)

Reads data/processed/training/ (scripts/build_training_set.py). Loss: multiple negatives ranking
with each triplet's hard negative; every other book in the batch is a negative too, so bigger
batches help, and the cached variant gets a big batch into 24 GB. The val fold scores each
checkpoint (nDCG@10 over the whole catalog) and the best one is saved to models/<name>-ft/,
which the `<name>-ft` embedding model loads (embed/models.py).
"""

import argparse
import json
import time
from pathlib import Path

DATA = Path("data/processed/training")
MPS_SEQ_LENGTH = 64  # see the note where it is used


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default="bge-base", help="embedding model to start from")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=None, help="default models/<base>-ft")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--mini-batch", type=int, default=0,
                        help="cached loss: forward this many at a time (0 = plain loss)")  # fmt: skip
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-steps", type=int, default=-1, help="stop early (debug runs)")
    parser.add_argument("--eval-steps", type=int, default=200)
    parser.add_argument("--max-seq-length", type=int, default=0, help="override (debug runs)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    import torch
    from datasets import Dataset  # training-only dependencies, imported when used
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
    )
    from sentence_transformers.base.sampler import BatchSamplers
    from sentence_transformers.sentence_transformer.evaluation import (
        InformationRetrievalEvaluator,
    )
    from sentence_transformers.sentence_transformer.losses import (
        CachedMultipleNegativesRankingLoss,
        MultipleNegativesRankingLoss,
    )

    from shelfwise.embed.encoder import own_memory, pick_device
    from shelfwise.embed.models import MODELS

    spec = MODELS[args.base]
    out = args.out or Path("models") / f"{args.base}-ft"
    device = pick_device()

    with (args.data / "embedder_train.jsonl").open() as f:
        rows = [json.loads(line) for line in f]
    train = Dataset.from_dict(
        {
            "anchor": [spec.query_prefix + r["anchor"] for r in rows],
            "positive": [r["positive"] for r in rows],
            "negative": [r["negative"] for r in rows],
        }
    )
    val = json.loads((args.data / "val.json").read_text())
    corpus = json.loads((args.data / "corpus.json").read_text())
    evaluator = InformationRetrievalEvaluator(
        queries=val["queries"],
        corpus=corpus,
        relevant_docs={q: set(keys) for q, keys in val["relevant"].items()},
        query_prompt=spec.query_prefix,
        name="val",
        batch_size=64,
        write_csv=False,
    )

    model = SentenceTransformer(spec.hf_id, device=device)
    own_memory(model)
    seq_length = args.max_seq_length or spec.max_seq_length
    if device == "mps" and not args.max_seq_length:
        # On the 8 GB Mac, training at 256+ tokens returned zero loss and a negative gradient
        # norm (2026-10-10): silent garbage, no update. 64 trains correctly; Mac runs are debug.
        seq_length = MPS_SEQ_LENGTH
        print(f"MPS: debug run, sequences cut to {seq_length} tokens (train for real on CUDA)")
    model.max_seq_length = seq_length
    loss = (
        CachedMultipleNegativesRankingLoss(model, mini_batch_size=args.mini_batch)
        if args.mini_batch
        else MultipleNegativesRankingLoss(model)
    )
    metrics = evaluator(model)
    key = next(k for k in metrics if k.endswith("cosine_ndcg@10"))
    before = metrics[key]
    print(f"base {args.base}: val nDCG@10 {before:.4f} ({len(val['queries'])} queries)")

    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(Path("checkpoints") / f"{args.base}-ft"),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        fp16=device == "cuda",
        # A repeated book in a batch would be its own in-batch negative.
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.eval_steps,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model=f"eval_{key}",
        logging_steps=20,
        seed=args.seed,
        report_to="none",
    )
    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train,
        loss=loss,
        evaluator=evaluator,
    )
    from shelfwise.training.guard import max_change, snapshot

    before_weights = snapshot(model)
    start = time.perf_counter()
    trainer.train()
    moved = max_change(model, before_weights)
    if moved == 0:
        raise SystemExit("training left the weights unchanged; not saving (see training/guard.py)")
    after = evaluator(model)[key]
    model.save(str(out))
    summary = {
        "base": spec.hf_id,
        "val_ndcg@10_before": round(before, 4),
        "val_ndcg@10_after": round(after, 4),
        "max_weight_change": moved,
        "train_rows": len(rows),
        "epochs": args.epochs,
        "max_steps": args.max_steps,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "max_seq_length": seq_length,
        "device": device,
        "torch": torch.__version__,
        "minutes": round((time.perf_counter() - start) / 60, 1),
        "data": json.loads((args.data / "manifest.json").read_text()),
    }
    (out / "shelfwise_training.json").write_text(json.dumps(summary, indent=1))
    print(f"val nDCG@10 {before:.4f} -> {after:.4f}; saved {out}/")


if __name__ == "__main__":
    main()
