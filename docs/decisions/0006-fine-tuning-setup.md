# 6. Fine-tuning the embedder and reranker: data, losses, and one locked test run

**Status:** accepted, 2026-10-10; runs on the GPU day · **Design doc:** §36, §40.1

## Context

Off-the-shelf models are good but generic: bge-base-en-v1.5 scores nDCG@10 0.643 on the dev split, and MiniLM's web-search reranker makes ranking *worse* (0.600 at its best depth). Hand-graded data is scarce: ~110 dev queries. Training time is a single ~1-day visit to an RTX 4090.

## Decision

- **Data** (`make training-set`): graded dev pairs (grade/3 as a soft label, judged-0 books as negatives) plus two synthetic requests per book written by Qwen3-8B (a mood one and a specific one, plot-free; requests that copy the title, author or a 5-word span of the blurb are dropped). Hard negatives are mined from the base model's ranks 10–60, other authors only.
- **Splits:** query families are split dev/test once; the test split is never read by training or tuning. Dev families are split again into train and val folds, and val picks checkpoints.
- **Embedder:** bge-base-en-v1.5, cached MultipleNegativesRankingLoss (big in-batch negatives in 24 GB), no-duplicate batches, best checkpoint by val nDCG@10 over the whole catalog.
- **Rerankers:** bge-base and MiniLM cross-encoders, binary cross-entropy on the soft labels.
- **One command** (`make gpu-day`): train, embed, evaluate on dev, re-sweep rerank depth, then run the **locked test split once**, for the base setup and the final one chosen on dev. The script records that the test split ran and refuses to run it again.
- A guard refuses to save weights that didn't change (MPS on the Mac silently trains nothing at 256+ tokens).

## Consequences

- Results are reported as dev gains with paired bootstrap CIs, and one test number per configuration, so the gain can't be tuned to the test set.
- ~110 graded queries is a small val set; the synthetic requests carry most of the training signal, and their style may differ from real readers'.
