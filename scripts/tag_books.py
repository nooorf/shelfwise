"""Tag books with the local LLM: darkness, romance, violence, pace, supernatural, audience,
fiction, historical setting, reading level and themes.

    uv run python scripts/tag_books.py --limit 20          # try a few first
    uv run python scripts/tag_books.py                     # everything untagged (resumable)
    uv run python scripts/tag_books.py --model qwen3:1.7b
    uv run python scripts/tag_books.py --labelled          # just your 200, then `make score-tags`

Needs `make llm` running. Stop any time with Ctrl-C and re-run: finished books are kept.
Themes feed each book's search text, so run `make embed` afterwards.
"""

import argparse
import time
from pathlib import Path

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.evaluation.judgments import work_keys
from shelfwise.llm.client import OllamaClient
from shelfwise.tagging.facets import BookRecord
from shelfwise.tagging.labels import load_labels
from shelfwise.tagging.tagger import tag_books

LABELS = Path("eval/data/facet_labels.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=get_settings().llm_model)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--labelled", action="store_true", help=f"only the works in {LABELS}")
    args = parser.parse_args()

    engine = make_engine()
    only = None
    if args.labelled:
        wanted = {label.work_key for label in load_labels(LABELS)}
        with engine.connect() as conn:
            only = [work_id for work_id, key in work_keys(conn).items() if key in wanted]
        print(f"{len(only)} of {len(wanted)} labelled works found in the catalog")

    start = time.perf_counter()

    def progress(done: int, total: int, book: BookRecord) -> None:
        rate = done / (time.perf_counter() - start)
        eta = (total - done) / rate if rate else 0
        print(f"  {done}/{total}  {book.title[:40]:40}  ~{eta / 60:.0f} min left", end="\r")

    stats = tag_books(engine, OllamaClient(model=args.model), args.limit, progress, only)
    per_book = stats.seconds / stats.tagged if stats.tagged else 0
    print(
        f"\ntagged {stats.tagged}, failed {stats.failed} (see ingest_error); "
        f"{per_book:.1f}s per book, {stats.completion_tokens} tokens generated"
    )
    if stats.tagged:
        print("next: `make embed` (themes are part of each book's search text)")


if __name__ == "__main__":
    main()
