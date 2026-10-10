"""Synthetic reader requests for each book, written by the local LLM.

The fine-tuned models need far more (request, book) pairs than a few hundred graded queries give.
For each book the LLM writes two requests a reader who doesn't know the book might make, in two
styles: a mood ("something cozy and a bit sad") and a specific wish (topic, setting, audience).
The record is the only source, so the requests can't mention anything the catalog doesn't
support; `reuses_record` then drops any that name the title or author or quote the blurb.

Bump PROMPT_VERSION when the prompt changes: generation skips books that already have requests
from the current version and model, and the training set records which version it used.
"""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from shelfwise.llm.client import Message
from shelfwise.tagging.facets import BookRecord

PROMPT_VERSION = "synq-v1"
STYLES = ("mood", "specific")
MAX_DESCRIPTION = 1200  # characters of the blurb shown; enough to know what the book is

SYSTEM = """You write requests that library visitors type or say when looking for something to \
read. You are given one book's catalog record. Write two requests from readers who have never \
heard of this book but would be happy to be handed it.

1. "mood": what they feel like reading, in their own casual words: tone, feeling, kind of story. \
4 to 14 words.
2. "specific": one or two concrete wishes the book meets: a topic, setting, period, audience, \
kind of character, or length. 6 to 20 words. May be phrased as a question. The reader doesn't \
know the plot, so ask in general terms ("a family stuck somewhere isolated in winter"), never \
summarize what happens.

Rules:
- Vary how the requests start, as different people would; don't open with "i need" or \
"can i get" every time.
- Never use the title, the author, character names, place names invented by the book, or the \
series name.
- Don't copy phrases from the description; say it the way a reader would.
- Only ask for things the record supports.
- Plain everyday English, lower case is fine, no quotation marks."""


class SyntheticOutput(BaseModel):
    mood: str = Field(min_length=8, max_length=160)
    specific: str = Field(min_length=12, max_length=200)


def build_messages(book: BookRecord, themes: Sequence[str] = ()) -> list[Message]:
    lines = [f"Title: {book.title}", "By: " + ", ".join(book.authors)]
    if book.genres:
        lines.append("Genres: " + ", ".join(book.genres))
    if themes:
        lines.append("Themes: " + ", ".join(themes))
    if book.subjects:
        lines.append("Reader shelves: " + ", ".join(book.subjects[:12]))
    if book.first_pub_year:
        lines.append(f"First published: {book.first_pub_year}")
    if book.description:
        lines.append("Description: " + book.description[:MAX_DESCRIPTION])
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]


def clean(text: str) -> str:
    return " ".join(text.strip().strip("\"'“”").split())
