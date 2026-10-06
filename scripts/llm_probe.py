"""Compare local LLMs on a small real task: tag 5 catalog books with a structured schema.

    uv run python scripts/llm_probe.py qwen3:1.7b qwen3:4b

Reports load time, per-book latency, generation speed and the model's memory footprint, plus
its answers so you can eyeball quality. A preview of the book-tagging step, not the real thing.
"""

import argparse
import time
from typing import Literal

import httpx2
from pydantic import BaseModel, Field
from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.llm.client import OllamaClient

TITLES = (
    "silent patient",
    "dune",
    "it",
    "before the coffee gets cold",
    "operating system concepts",
)


class QuickTags(BaseModel):
    darkness: int = Field(ge=0, le=3, description="0 light and cheerful ... 3 very dark")
    supernatural: Literal["yes", "no", "unclear"]
    audience: Literal["children", "ya", "adult"]
    fiction: bool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+")
    args = parser.parse_args()

    with make_engine().connect() as conn:
        books = conn.execute(
            text("SELECT title, description FROM work WHERE title_norm = ANY(:t) ORDER BY title"),
            {"t": list(TITLES)},
        ).all()

    for model in args.models:
        client = OllamaClient(model=model)
        latencies, speeds, load_ms = [], [], 0.0
        print(f"\n== {model}")
        for book in books:
            start = time.perf_counter()
            result = client.chat_structured(
                [
                    {
                        "role": "system",
                        "content": "You tag library books. Answer only from the description.",
                    },
                    {
                        "role": "user",
                        "content": f"Title: {book.title}\nDescription: {(book.description or '')[:1200]}",
                    },
                ],
                QuickTags,
                max_tokens=96,
            )
            elapsed = (time.perf_counter() - start) * 1000
            load_ms += result.stats.load_ms
            latencies.append(elapsed - result.stats.load_ms)
            speeds.append(result.stats.tokens_per_second)
            v = result.value
            print(f"  {book.title[:30]:30} dark={v.darkness} supernatural={v.supernatural:7} "
                  f"audience={v.audience:8} fiction={v.fiction}  ({elapsed:.0f} ms)")  # fmt: skip
        loaded = httpx2.get(f"{get_settings().ollama_url}/api/ps").json().get("models", [])
        size = next((m.get("size", 0) for m in loaded if m["name"] == model), 0) / 1024**3
        print(
            f"  load {load_ms / 1000:.1f}s | per book {sorted(latencies)[len(latencies) // 2]:.0f} ms (median) | "
            f"{sum(speeds) / len(speeds):.0f} tok/s | in memory {size:.1f} GB"
        )


if __name__ == "__main__":
    main()
