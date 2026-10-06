"""The text each book is embedded as (design doc §11.1).

One document per work, no chunking: descriptions fit easily in every model's context. Fields that
change often or carry no meaning (availability, shelf, copies, ISBN, publisher) are excluded on
purpose, so circulation never forces a re-embed. Titles and authors are included once; exact name
matching is BM25's job, not the embedding's.
"""

import hashlib
from collections.abc import Sequence

MAX_TAGS = 20


def build_search_text(
    title: str,
    subtitle: str | None = None,
    authors: Sequence[str] = (),
    genres: Sequence[str] = (),
    themes: Sequence[str] = (),
    tags: Sequence[str] = (),
    description: str | None = None,
) -> str:
    lines = [f"Title: {title}" + (f": {subtitle}" if subtitle else "")]
    if authors:
        lines.append("By: " + ", ".join(authors))
    if genres:
        lines.append("Genres: " + "; ".join(genres))
    if themes:
        lines.append("Themes: " + "; ".join(themes))
    if tags:
        lines.append("Subjects: " + "; ".join(tags[:MAX_TAGS]))
    if description:
        lines.append("About: " + description)
    return "\n".join(lines)


def content_hash(search_text: str) -> str:
    return hashlib.sha256(search_text.encode()).hexdigest()[:32]
