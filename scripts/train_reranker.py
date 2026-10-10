"""Fine-tune the cross-encoder reranker on the training set (Phase 7).

    uv run python scripts/train_reranker.py --base minilm --max-steps 30    # smoke test on the Mac
    uv run python scripts/train_reranker.py --base bge-base --epochs 1      # the real run (4090)

Reads data/processed/training/ (scripts/build_training_set.py). Loss: binary cross-entropy on
soft labels: graded pairs keep their grade (0, 1/3, 2/3, 1), so "partly related" stays between
yes and no; synthetic pairs are 1 or 0. The val fold scores each checkpoint by reranking the base
embedder's top 30 per query (nDCG@10) and the best one is saved to models/<name>-rerank-ft/, which
the `<name>-ft` reranker loads (ranking/rerank.py).
"""

import argparse
import json
import time
from pathlib import Path

DATA = Path("data/processed/training")
MPS_MAX_LENGTH = 64  # MPS training is unreliable at longer inputs; see train_embedder.py


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default="bge-base", help="reranker to start from")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=None, help="default models/<base>-rerank-ft")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-steps", type=int, default=-1, help="stop early (debug runs)")
    parser.add_argument("--eval-steps", type=int, default=200)
    parser.add_argument("--max-length", type=int, default=0, help="override (debug runs)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    import torch
    from datasets import Dataset  # training-only dependencies, imported when used
    from sentence_transformers import (
        CrossEncoder,
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
    )
    from sentence_transformers.cross_encoder.evaluation import CrossEncoderRerankingEvaluator
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

    from shelfwise.embed.encoder import own_memory, pick_device
    from shelfwise.ranking.rerank import MODELS

    spec = MODELS[args.base]
    out = args.out or Path("models") / f"{args.base}-rerank-ft"
    device = pick_device()

    with (args.data / "reranker_train.jsonl").open() as f:
        rows = [json.loads(line) for line in f]
    train = Dataset.from_dict(
        {
            "query": [r["query"] for r in rows],
            "document": [r["document"] for r in rows],
            "label": [float(r["label"]) for r in rows],
        }
    )
    val = json.loads((args.data / "val.json").read_text())
    corpus = json.loads((args.data / "corpus.json").read_text())
    samples = [
        {
            "query": text,
            "positive": [corpus[k] for k in val["relevant"][qid]],
            "documents": [corpus[k] for k in val["candidates"][qid]],
        }
        for qid, text in val["queries"].items()
    ]
    evaluator = CrossEncoderRerankingEvaluator(
        samples, at_k=10, name="val", batch_size=32, write_csv=False
    )

    max_length = args.max_length or spec.max_length
    if device == "mps" and not args.max_length:
        max_length = MPS_MAX_LENGTH
        print(f"MPS: debug run, inputs cut to {max_length} tokens (train for real on CUDA)")
    model = CrossEncoder(spec.hf_id, device=device, max_length=max_length, num_labels=1)
    own_memory(model)
    loss = BinaryCrossEntropyLoss(model)
    metrics = evaluator(model)
    key = next(k for k in metrics if k.endswith("ndcg@10"))
    before = metrics[key]
    print(f"base {args.base}: val nDCG@10 {before:.4f} ({len(samples)} queries, top 30 reranked)")

    training_args = CrossEncoderTrainingArguments(
        output_dir=str(Path("checkpoints") / f"{args.base}-rerank-ft"),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        fp16=device == "cuda",
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
    trainer = CrossEncoderTrainer(
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
        "max_length": max_length,
        "device": device,
        "torch": torch.__version__,
        "minutes": round((time.perf_counter() - start) / 60, 1),
        "data": json.loads((args.data / "manifest.json").read_text()),
    }
    (out / "shelfwise_training.json").write_text(json.dumps(summary, indent=1))
    print(f"val nDCG@10 {before:.4f} -> {after:.4f}; saved {out}/")


if __name__ == "__main__":
    main()
