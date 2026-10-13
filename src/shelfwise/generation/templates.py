"""Replies built from the record alone: the fallback when the LLM is down or keeps failing the
validator. Always correct, never fluent."""

from typing import Literal

from shelfwise.generation.context import Candidate

Task = Literal["recommend", "explain", "compare"]
_SCALE = {0: "not at all", 1: "a little", 2: "fairly", 3: "very"}


def _kind(c: Candidate) -> str:
    kind = f"{c.genres[0]} book" if c.genres else "book"
    article = "An" if kind[:1].lower() in "aeiou" else "A"
    return f"{article} {kind}"


def why(c: Candidate) -> str:
    facts = [str(c.year)] if c.year else []
    if c.pages:
        facts.append(f"{c.pages} pages")
    sentence = _kind(c) + (f" ({', '.join(facts)})" if facts else "")
    if c.matched:
        return f"{sentence}; it fits: {', '.join(c.matched)}."
    return f"{sentence}."


def explain(c: Candidate) -> str:
    """The record, plainly: the first sentence or two of the description, or the facts."""
    if c.description:
        sentences = c.description.split(". ")
        return ". ".join(sentences[:2]).rstrip(".…") + "."
    return why(c)


def compare(c: Candidate) -> str:
    tags = [
        f"{name} {_SCALE[value]}"
        for name in ("darkness", "romance", "violence")
        if isinstance(value := c.facets.get(name), int)
    ]
    if pace := c.facets.get("pace"):
        tags.append(f"{pace} pace")
    return why(c).removesuffix(".") + (f"; {', '.join(tags)}." if tags else ".")


def intro(task: Task, count: int) -> str:
    if task == "explain":
        return "Here's what the catalog says."
    if task == "compare":
        return "Here they are side by side."
    return f"Here {'is a book' if count == 1 else f'are {count} books'} that fit."


def for_task(task: Task, c: Candidate) -> str:
    return {"recommend": why, "explain": explain, "compare": compare}[task](c)
