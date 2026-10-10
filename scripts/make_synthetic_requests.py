"""Write two synthetic reader requests per book with the local LLM (training data, Phase 7).

    uv run python scripts/make_synthetic_requests.py --limit 20             # look at a few first
    uv run python scripts/make_synthetic_requests.py --model qwen3:8b       # every book (resumable)

Needs Ollama (`make llm`, or the 4090 through the tunnel with SHELFWISE_OLLAMA_URL). Appends to
data/training/synthetic_requests.jsonl as it goes; Ctrl-C and re-run to resume. Requests that name
the title or author or quote the blurb are kept in the file but marked rejected, so the reject rate
can be reported. Then `scripts/build_training_set.py`.
"""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.evaluation.judgments import work_keys
from shelfwise.llm.client import LLMInvalidOutput, OllamaClient
from shelfwise.tagging.facets import BookRecord
from shelfwise.training.data import SyntheticRequest, load_synthetic, reuses_record
from shelfwise.training.synthetic import (
    PROMPT_VERSION,
    STYLES,
    SyntheticOutput,
    build_messages,
    clean,
)

OUT = Path("data/training/synthetic_requests.jsonl")

_BOOKS_SQL = text(
    """
    SELECT w.work_id, w.title, w.genres, w.tags, w.description, w.first_pub_year,
           coalesce(w.themes, '{}') AS themes,
           coalesce((SELECT array_agg(a.display ORDER BY wa.position)
                       FROM work_author wa JOIN author a USING (author_id)
                      WHERE wa.work_id = w.work_id), '{}') AS authors
    FROM work w
    ORDER BY w.work_id
    """
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=get_settings().llm_model)
    parser.add_argument("--limit", type=int, default=None, help="only the first N books to do")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    llm = OllamaClient(model=args.model, timeout=180)
    done = {
        r.work_key
        for r in load_synthetic(args.out)
        if r.model == args.model and r.prompt_version == PROMPT_VERSION
    }
    with make_engine().connect() as conn:
        keys = work_keys(conn)
        rows = [r for r in conn.execute(_BOOKS_SQL) if keys[r.work_id] not in done]
    rows = rows[: args.limit] if args.limit else rows
    print(f"{len(done)} books already done; writing requests for {len(rows)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    start, failed, rejected = time.perf_counter(), 0, 0
    with args.out.open("a", encoding="utf-8") as f:
        for i, r in enumerate(rows, start=1):
            book = BookRecord(
                r.work_id, r.title, r.authors, r.genres, r.tags, r.description, r.first_pub_year
            )
            try:
                result = llm.chat_structured(
                    build_messages(book, r.themes),
                    SyntheticOutput,
                    temperature=0.7,  # varied phrasing across books; seeded, so reproducible
                    seed=r.work_id,
                    max_tokens=200,
                )
            except LLMInvalidOutput:
                failed += 1
                continue
            for style in STYLES:
                request = clean(getattr(result.value, style))
                why = reuses_record(request, r.title, r.authors, r.description) or ""
                rejected += bool(why)
                row = SyntheticRequest(
                    keys[r.work_id], request, style, args.model, PROMPT_VERSION, why
                )
                f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            f.flush()
            rate = i / (time.perf_counter() - start)
            print(f"  {i}/{len(rows)}  {r.title[:40]:40}  ~{(len(rows) - i) / rate / 60:.0f} min left",
                  end="\r")  # fmt: skip
    total = 2 * (len(rows) - failed)
    print(f"\ndone: {len(rows) - failed} books, {failed} failed, "
          f"{rejected} of {total} requests rejected (named the book or copied the blurb)")  # fmt: skip


if __name__ == "__main__":
    main()
