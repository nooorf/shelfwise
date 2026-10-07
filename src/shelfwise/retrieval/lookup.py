"""Known-item lookup: ISBNs, and typo-tolerant title/author matching with pg_trgm (§13.2).

Title score, in two steps:

1. Trigram `word_similarity` in both directions: the title inside the query ("do you have the
   silent pateint") and the query inside the title (a partial title like "harry potter goblet").
2. Times title *coverage*: the share of the title's content words present in the query, allowing
   typos. This suppresses partial-word hits such as "Dickens" -> *Moby Dick*, "twist" ->
   *Oliver Twist*. Very short titles ("It") are also scaled down, since they match too easily.
3. Times *query* coverage: the share of the request's content words the title accounts for. A
   lookup names a book; a title that explains one word of a longer request ("take *home* today")
   isn't one, and the full title beats fragments of it (*Half-Blood* vs *...Half-Blood Prince*).

Authors: people often give only a surname ("works by Dickens"), so an exact surname counts
strongly, unless the surname is also an ordinary word in the catalog's titles ("young adult" is
not Samantha Young); then the first name must be there too.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import Connection, text

from shelfwise.ingest.normalize import fold_text, normalize_isbn
from shelfwise.retrieval.lexical import QUERY_FILLER

MIN_TITLE_SCORE = 0.45
MIN_AUTHOR_SCORE = 0.7  # below this, trigram look-alikes pass ("home" ~ Homer at 0.67)
SURNAME_MATCH_SCORE = 0.7
_CANDIDATES = 25
_TYPO_RATIO = 80  # rapidfuzz ratio for "same word, with a typo"
_TITLE_STOPWORDS = {"the", "a", "an", "and", "of", "on", "in", "to", "s", "for", "with", "or"}
# Words of a request that aren't part of a title: left out when measuring query coverage.
_REQUEST_WORDS = QUERY_FILLER | _TITLE_STOPWORDS | {
    "do", "you", "have", "has", "is", "are", "there", "any", "got", "i", "me", "my", "can",
    "could", "by", "what", "which", "where", "find", "get", "copy", "copies", "available",
    "checked", "out", "shelf", "library", "today", "now", "um", "ideally", "edition", "older",
}  # fmt: skip
QUERY_COVERAGE_FLOOR = 0.4  # a title covering none of the request keeps this share of its score
COMMON_WORD_TITLES = 2  # a surname found in this many titles is also an ordinary word
_FULL_CONFIDENCE_LENGTH = 6  # titles shorter than this (folded chars) get a proportional penalty
_ISBN_CANDIDATE = re.compile(r"(?<![\dXx])[\dXx][\dXx-]{8,15}[\dXx](?![\dXx])")


@dataclass(frozen=True)
class TitleMatch:
    work_id: int
    title: str
    score: float


@dataclass(frozen=True)
class AuthorMatch:
    author_id: int
    name: str
    score: float
    work_ids: tuple[int, ...]


def isbns_in(query: str) -> list[str]:
    return list(
        dict.fromkeys(i for c in _ISBN_CANDIDATE.findall(query) if (i := normalize_isbn(c)))
    )


def find_by_isbn(conn: Connection, query: str) -> list[int]:
    isbns = isbns_in(query)
    if not isbns:
        return []
    return list(
        conn.execute(
            text("SELECT DISTINCT work_id FROM edition WHERE isbn13 = ANY(:isbns)"),
            {"isbns": isbns},
        ).scalars()
    )


def _word_present(word: str, query_words: list[str]) -> bool:
    return any(
        word == q or (len(word) > 3 and fuzz.ratio(word, q) >= _TYPO_RATIO) for q in query_words
    )


def title_coverage(title_norm: str, query_words: list[str]) -> float:
    words = title_norm.split()
    content = [w for w in words if w not in _TITLE_STOPWORDS] or words
    return sum(_word_present(w, query_words) for w in content) / len(content)


def find_titles(
    conn: Connection, query: str, limit: int = 5, min_score: float = MIN_TITLE_SCORE
) -> list[TitleMatch]:
    folded = fold_text(query)
    if not folded:
        return []
    rows = conn.execute(
        text(
            """
            SELECT work_id, title, title_norm,
                   greatest(word_similarity(title_norm, :q), word_similarity(:q, title_norm))
                     * least(1.0, length(title_norm)::float / :full) AS trigram
            FROM work
            ORDER BY trigram DESC, work_id
            LIMIT :candidates
            """
        ),
        {"q": folded, "full": _FULL_CONFIDENCE_LENGTH, "candidates": _CANDIDATES},
    )
    query_words = folded.split()
    request = [w for w in query_words if w not in _REQUEST_WORDS] or query_words
    scored = [
        TitleMatch(
            r.work_id,
            r.title,
            float(r.trigram)
            * (0.5 + 0.5 * title_coverage(r.title_norm, query_words))
            * (
                QUERY_COVERAGE_FLOOR
                + (1 - QUERY_COVERAGE_FLOOR)
                * title_coverage(" ".join(request), r.title_norm.split())
            ),
        )
        for r in rows
    ]
    scored.sort(key=lambda m: (-m.score, m.work_id))
    return [m for m in scored if m.score >= min_score][:limit]


def find_authors(
    conn: Connection, query: str, limit: int = 3, min_score: float = MIN_AUTHOR_SCORE
) -> list[AuthorMatch]:
    folded = fold_text(query)
    if not folded:
        return []
    rows = conn.execute(
        text(
            """
            SELECT a.author_id, a.display, a.name_norm,
                   word_similarity(a.name_norm, :q) AS trigram,
                   array_agg(wa.work_id ORDER BY wa.work_id) AS work_ids
            FROM author a JOIN work_author wa USING (author_id)
            GROUP BY a.author_id
            -- Surname matches first, so they're never crowded out of the candidate list.
            ORDER BY regexp_replace(a.name_norm, '^.* ', '') = ANY(:words) DESC,
                     trigram DESC, a.author_id
            LIMIT :candidates
            """
        ),
        {"q": folded, "words": folded.split(), "candidates": _CANDIDATES},
    )
    query_words = set(folded.split())
    rows = list(rows)
    common = _ordinary_words(conn, {r.name_norm.split()[-1] for r in rows} & query_words)
    matches = []
    for r in rows:
        names = r.name_norm.split()
        surname = names[-1]
        score = float(r.trigram)
        if len(surname) >= 4 and surname in query_words:
            first_name_given = len(names) > 1 and names[0] in query_words
            if surname not in common or first_name_given:
                score = max(score, SURNAME_MATCH_SCORE)
            else:
                score = min(score, MIN_AUTHOR_SCORE - 0.01)  # "young adult" is not Samantha Young
        matches.append(AuthorMatch(r.author_id, r.display, score, tuple(r.work_ids)))
    matches.sort(key=lambda m: (-m.score, m.author_id))
    return [m for m in matches if m.score >= min_score][:limit]


def _ordinary_words(conn: Connection, words: set[str]) -> set[str]:
    """Which of `words` also occur as ordinary words in at least COMMON_WORD_TITLES titles."""
    if not words:
        return set()
    rows = conn.execute(
        text(
            """
            SELECT w.word FROM unnest(CAST(:words AS text[])) AS w(word)
            WHERE (SELECT count(*) FROM work
                    WHERE title_norm ~ ('(^| )' || w.word || '( |$)')) >= :n
            """
        ),
        {"words": sorted(words), "n": COMMON_WORD_TITLES},
    )
    return {r.word for r in rows}
