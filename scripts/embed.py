"""Rebuild each book's search text, then embed books whose text changed since the last run.

    uv run python scripts/embed.py                    # the default model (settings.embedding_model)
    uv run python scripts/embed.py --model qwen3-0.6b
    uv run python scripts/embed.py --model all        # every model in the comparison

Safe to re-run: unchanged books are skipped. Models download on first use (~0.1-1.2 GB each).
"""

import argparse
import time

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.embed.encoder import load_embedder
from shelfwise.embed.models import MODELS
from shelfwise.embed.store import embed_missing, refresh_search_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=get_settings().embedding_model, choices=[*MODELS, "all"])
    args = parser.parse_args()
    names = list(MODELS) if args.model == "all" else [args.model]

    with make_engine().begin() as conn:
        print(f"search text updated for {refresh_search_text(conn)} books")

    for name in names:
        start = time.perf_counter()
        embedder = load_embedder(name)
        with make_engine().begin() as conn:
            count = embed_missing(
                conn,
                embedder,
                progress=lambda done, total, name=name: print(
                    f"  {name}: {done}/{total}", end="\r"
                ),
            )
        elapsed = time.perf_counter() - start
        print(f"{name}: embedded {count} books in {elapsed:.1f}s" + " " * 20)


if __name__ == "__main__":
    main()
