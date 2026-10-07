"""The book record shown by the terminal labelling tools: title, author, year, pages, genres,
subjects and description. Never the LLM's tags, so they can't sway a human label."""

import textwrap
from typing import Any

from sqlalchemy import Row, text

MAX_SUBJECTS = 15
MAX_DESCRIPTION = 1200

BOOK_SQL = text(
    """
    SELECT w.work_id, w.title, w.subtitle, w.first_pub_year, w.genres, w.tags, w.description,
           (SELECT string_agg(a.display, ', ' ORDER BY wa.position) FROM work_author wa
              JOIN author a USING (author_id) WHERE wa.work_id = w.work_id) AS authors,
           (SELECT max(e.pages) FROM edition e WHERE e.work_id = w.work_id) AS pages
    FROM work w
    """
)


def show(book: Row[Any], position: int, total: int) -> None:
    title = book.title + (f": {book.subtitle}" if book.subtitle else "")
    print("\n" + "=" * 78)
    print(f"[{position}/{total}]  {title}")
    print(f"   {book.authors or 'unknown author'} · {book.first_pub_year or '?'} · "
          f"{book.pages or '?'} pages · {', '.join(book.genres) or 'no genres'}")  # fmt: skip
    if book.tags:
        subjects = "subjects: " + ", ".join(book.tags[:MAX_SUBJECTS])
        print(textwrap.fill(subjects, 77, initial_indent="   ", subsequent_indent="   "))
    print("-" * 78)
    description = (book.description or "(no description)")[:MAX_DESCRIPTION]
    print(textwrap.indent(textwrap.fill(description, 74), "   "))
    print("-" * 78)
