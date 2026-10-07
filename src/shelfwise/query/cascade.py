"""Query understanding as a cascade (design doc §12.2).

    rules -> LLM form -> entity linking -> merge -> sanity checks

1. Rules find numbers, dates, availability and ISBNs; they're authoritative for those.
2. The LLM fills `QueryLLM` (intent, books, genres, moods, negations); `to_constraints` turns
   that into constraints with fixed conventions.
3. Book and author names the LLM wrote are linked to catalog spellings. A weak match is
   dropped rather than trusted: "harry potter 8" must stay itself, not become Azkaban.
4. Merge: rule constraints win their fields; a title lookup drops `available_now` (status is
   always shown); negated words are removed from the semantic query.
5. Sanity: intent must fit what was found (a lookup needs something to look up, `similar`
   needs a seed). If the LLM is down or answers badly twice, the rules-only parse is returned.
"""

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import structlog
from rapidfuzz import fuzz
from sqlalchemy import Connection

from shelfwise.ingest.normalize import fold_text
from shelfwise.llm.client import LLMInvalidOutput, LLMUnavailable, StructuredLLM
from shelfwise.query.constraints import Constraint
from shelfwise.query.extract import QueryLLM, build_messages, negated_words, to_constraints
from shelfwise.query.request import LookupSpec, ParsedRequest, constraint_problems, from_rules
from shelfwise.query.rules import RuleParse, parse_rules
from shelfwise.retrieval.lookup import find_authors, find_titles

log = structlog.get_logger(__name__)

LINK_TITLE_SCORE = 0.7  # below this, find_titles mostly returns a different book
_RULE_FIELDS = frozenset({"pages", "year", "available_now", "isbn"})
_NEGATION_CUES = re.compile(
    r"\b(?:no|not|without|nothing|except|none|less|isn'?t|doesn'?t|don'?t)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Link:
    name: str  # the catalog's spelling
    work_id: int | None = None


class Linker(Protocol):
    def title(self, text: str) -> Link | None: ...
    def author(self, text: str) -> Link | None: ...


class CatalogLinker:
    """Links against the catalog with the known-item lookup's matchers."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def title(self, text: str) -> Link | None:
        matches = find_titles(self.conn, text, limit=1, min_score=LINK_TITLE_SCORE)
        return Link(matches[0].title, matches[0].work_id) if matches else None

    def author(self, text: str) -> Link | None:
        matches = find_authors(self.conn, text, limit=1)
        if not matches:
            return None
        # Every word given must be in the name: "james clear" is not E. L. James.
        name_words = fold_text(matches[0].name).split()
        given = [w for w in fold_text(text).split() if len(w) > 1]
        if not all(any(fuzz.ratio(w, n) >= 80 for n in name_words) for w in given):
            return None
        return Link(matches[0].name)


@dataclass(frozen=True)
class CascadeResult:
    request: ParsedRequest
    used_llm: bool
    llm_ms: float = 0.0
    error: str | None = None  # why the LLM step was skipped or failed


def strip_words(text: str, words: list[str]) -> str:
    """Remove negated words (and plurals) and dangling negation cues from the semantic query.

    Works on the original text, so "c++" or "data-intensive" reach the embedder intact."""
    if not words:
        return text.strip()
    for word in sorted({w.strip().lower() for w in words if w.strip()}, key=len, reverse=True):
        pattern = r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", word)))
        text = re.sub(rf"\b{pattern}(?:s|es)?\b", " ", text, flags=re.IGNORECASE)
    text = _NEGATION_CUES.sub(" ", text)
    text = re.sub(r"\s+([,.;])", r"\1", " ".join(text.split()))
    return re.sub(r"^[\s,.;]+|[\s,;]+$|,(?=[\s,]*,)", "", text)


def merge(rules: RuleParse, out: QueryLLM, linker: Linker) -> ParsedRequest:
    """Combine the rule parse and the LLM's form into one request (steps 3-5)."""
    llm_constraints = [
        c for c in to_constraints(out) if c.field not in _RULE_FIELDS or c.op == "shift"
    ]
    constraints: list[Constraint] = [*rules.constraints]
    for c in llm_constraints:
        if problems := constraint_problems(c.field, c.op, c.value):
            log.warning("parser.invalid_constraint", problems=problems)
            continue
        constraints.append(c)

    title = author = title_link = None
    if out.lookup_title:
        title_link = linker.title(out.lookup_title)
        title = title_link.name if title_link else out.lookup_title
    if out.lookup_author:
        link = linker.author(out.lookup_author)
        author = link.name if link else out.lookup_author
    seeds, seed_ids = [], []
    for name in dict.fromkeys(out.similar_to):
        link = linker.title(name)
        seeds.append(link.name if link else name)
        if link and link.work_id is not None:
            seed_ids.append(link.work_id)

    intent = out.intent
    if intent == "similar" and not seeds and title:  # the model put the seed in the wrong slot
        seeds, title = [title], None
        if title_link and title_link.work_id is not None:
            seed_ids.append(title_link.work_id)
    if any(c.field == "isbn" for c in constraints):
        intent = "lookup"
    elif intent == "lookup" and not (title or author):
        intent = "similar" if seeds else "discover"
    elif intent in ("discover", "refine") and seeds:
        intent = "similar"
    elif intent == "similar" and not seeds:
        intent = "discover"
    if intent != "lookup":
        title = None  # only a lookup is about one named book; an author can narrow any search
    elif title:
        constraints = [c for c in constraints if c.field != "available_now"]

    semantic = strip_words(out.semantic_query or rules.residual, negated_words(out))
    return ParsedRequest(
        intent=intent,
        semantic_query=semantic,
        lookup=LookupSpec(title=title, author=author) if (title or author) else None,
        seed_titles=seeds,
        seed_work_ids=seed_ids,
        constraints=constraints,
    )


class CascadeParser:
    def __init__(self, llm: StructuredLLM, linker: Linker) -> None:
        self.llm = llm
        self.linker = linker

    def parse(self, query: str, today: date | None = None) -> CascadeResult:
        rules = parse_rules(query, today)
        messages = build_messages(query, [c.span for c in rules.constraints if c.span])
        start = time.perf_counter()
        try:
            result = self.llm.chat_structured(messages, QueryLLM, max_tokens=300)
        except (LLMUnavailable, LLMInvalidOutput) as exc:
            log.warning("parser.llm_failed", error=str(exc))
            return CascadeResult(from_rules(rules), used_llm=False, error=str(exc))
        elapsed = (time.perf_counter() - start) * 1000
        return CascadeResult(merge(rules, result.value, self.linker), used_llm=True, llm_ms=elapsed)
