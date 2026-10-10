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

The same score is also taken for the main title alone ("seabiscuit" is *Seabiscuit: An American
Legend*), and a *spelling* score stands in when higher: the request and the title compared letter
by letter without spaces, which forgives typos and misheard splits ("frankenstien", "frank and
steen"). Numbers must agree exactly ("harry potter 8" is not *Harry Potter*), and short requests
never count on spelling alone.

Authors: people often give only a surname ("works by Dickens"), so an exact surname counts
strongly, unless the surname is also an ordinary word in the catalog's titles ("young adult" is
not Samantha Young); then the first name must be there too.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy import Connection, text

from shelfwise.ingest.normalize import (
    fold_text,
    normalize_isbn,
    number_variants,
    split_title,
    title_norm,
)
from shelfwise.retrieval.lexical import QUERY_FILLER

MIN_TITLE_SCORE = 0.45
MIN_AUTHOR_SCORE = 0.7  # below this, trigram look-alikes pass ("home" ~ Homer at 0.67)
SURNAME_MATCH_SCORE = 0.7
_CANDIDATES = 25
_TYPO_RATIO = 80  # rapidfuzz ratio for "same word, with a typo"
_TITLE_STOPWORDS = {"the", "a", "an", "and", "of", "on", "in", "to", "s", "for", "with", "or"}
# Words of a request that aren't part of a title: left out when measuring query coverage.
REQUEST_WORDS = QUERY_FILLER | _TITLE_STOPWORDS | {
    "do", "you", "have", "has", "is", "are", "there", "any", "got", "i", "me", "my", "can",
    "could", "by", "what", "which", "where", "find", "get", "copy", "copies", "available",
    "checked", "out", "shelf", "library", "today", "now", "um", "ideally", "edition", "older",
}  # fmt: skip
QUERY_COVERAGE_FLOOR = 0.4  # a title covering none of the request keeps this share of its score
COMMON_WORD_TITLES = 2  # a surname found in this many titles is also an ordinary word
_FULL_CONFIDENCE_LENGTH = 6  # titles shorter than this (folded chars) get a proportional penalty
SPELLING_MIN_CHARS = 6  # shorter requests never match on spelling alone ("the girl" ~ The Girls)
EXACT_MIN_CHARS = 4  # "dune" is Dune; "it" in "is it checked out" is just a word
SPELLING_SCORE = 0.85  # a spelling this close counts as the title; below, it's only a guess
# "Did you mean": a title is worth offering at this score or spelling, an author at this
# spelling. Made-up titles in grounding set E reach 0.74 spelling at most; misspelled and
# misheard real ones 0.75-0.85 ("frank and steen" ~ Frankenstein 0.80).
GUESS_SCORE = 0.6
GUESS_SPELLING = 0.75
MAX_GUESSES = 3
_SPELLING_CANDIDATES = 10
_DIGITS = re.compile(r"\d+")
_ISBN_CANDIDATE = re.compile(r"(?<![\dXx])[\dXx][\dXx-]{8,15}[\dXx](?![\dXx])")


@dataclass(frozen=True)
class TitleMatch:
    work_id: int
    title: str
    score: float
    spelling: float = 0.0  # letter-by-letter closeness to the main title, for "did you mean"


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
    """Catalog titles matching `query`, best first. Numbers are also tried as the catalog may
    spell them ("1984" finds Nineteen Eighty-Four, "henry the eighth" finds Henry VIII)."""
    scored = sorted(_title_matches(conn, query), key=lambda m: (-m.score, m.work_id))
    return [m for m in scored if m.score >= min_score][:limit]


def guess_titles(conn: Connection, name: str) -> list[TitleMatch]:
    """Titles the reader may have meant by a `name` that didn't match ("frank and steen",
    "the hobit"), most likely first, one per spelling; [] when nothing is close."""
    close = [
        m for m in _title_matches(conn, name)
        if m.score >= GUESS_SCORE or m.spelling >= GUESS_SPELLING
    ]  # fmt: skip
    close.sort(key=lambda m: (-(m.score + m.spelling), m.work_id))
    seen: set[str] = set()
    out = []
    for m in close:
        if (key := fold_text(m.title)) not in seen:
            seen.add(key)
            out.append(m)
    return out[:MAX_GUESSES]


def guess_authors(conn: Connection, name: str) -> list[str]:
    """Catalog authors spelled like `name` ("neil gayman", "steven king"), closest first."""
    asked = fold_text(name).replace(" ", "")
    if len(asked) < SPELLING_MIN_CHARS:
        return []
    names = conn.execute(
        text("SELECT DISTINCT a.display FROM author a JOIN work_author wa USING (author_id)")
    ).scalars()
    spelled = {display: fold_text(display).replace(" ", "") for display in names}
    found = process.extract(
        asked, spelled, scorer=fuzz.ratio, score_cutoff=GUESS_SPELLING * 100, limit=MAX_GUESSES
    )
    return [display for _, _, display in found]


def _title_matches(conn: Connection, query: str) -> list[TitleMatch]:
    """Every candidate title for `query`, best per work over its number spellings."""
    folded = fold_text(query)
    if not folded:
        return []
    best: dict[int, TitleMatch] = {}
    for spelled in (folded, *number_variants(folded)):
        for match in _score_titles(conn, spelled):
            old = best.get(match.work_id)
            if old is None or (match.score, match.spelling) > (old.score, old.spelling):
                best[match.work_id] = match
    return list(best.values())


def _score_titles(conn: Connection, folded: str) -> list[TitleMatch]:
    query_words = folded.split()
    request = [w for w in query_words if w not in REQUEST_WORDS] or query_words
    asked = title_norm(" ".join(w for w in query_words if w not in _ASKING)).replace(" ", "")
    rows = conn.execute(
        text(
            """
            (SELECT work_id, title, title_norm,
                    greatest(word_similarity(title_norm, :q), word_similarity(:q, title_norm))
                      * least(1.0, length(title_norm)::float / :full) AS trigram
             FROM work ORDER BY trigram DESC, work_id LIMIT :candidates)
            UNION
            (SELECT work_id, title, title_norm,
                    greatest(word_similarity(title_norm, :q), word_similarity(:q, title_norm))
                      * least(1.0, length(title_norm)::float / :full) AS trigram
             FROM work ORDER BY similarity(replace(title_norm, ' ', ''), :spelled) DESC, work_id
             LIMIT :spelling_candidates)
            """
        ),
        {"q": folded, "full": _FULL_CONFIDENCE_LENGTH, "candidates": _CANDIDATES,
         "spelled": asked, "spelling_candidates": _SPELLING_CANDIDATES},
    )  # fmt: skip
    rows = list(rows)
    # How many titles start with the request: two or more and it names a series ("harry
    # potter"), not the one book whose main title it happens to be (*Harry Potter: Film
    # Wizardry*); then main titles get no boost.
    spaced = title_norm(" ".join(w for w in query_words if w not in _ASKING))
    series = sum(r.title_norm.startswith(f"{spaced} ") for r in rows) >= 2
    matches = []
    for r in rows:
        main = title_norm(split_title(r.title)[0])
        if series and main != r.title_norm:
            main = r.title_norm
        norms = [r.title_norm, *([main] if _numbers(main) == _numbers(asked) else [])]
        score = max(_word_score(float(r.trigram), n, query_words, request) for n in norms)
        spelled = spelling(asked, main)
        matches.append(TitleMatch(
            r.work_id, r.title, max(score, spelled if spelled >= SPELLING_SCORE else 0.0), spelled
        ))  # fmt: skip
    return matches


# Words that ask for a book rather than name it; title words ("the", "of") stay in.
_ASKING = REQUEST_WORDS - _TITLE_STOPWORDS


def _word_score(trigram: float, norm: str, query_words: list[str], request: list[str]) -> float:
    return (
        trigram
        * (0.5 + 0.5 * title_coverage(norm, query_words))
        * (
            QUERY_COVERAGE_FLOOR
            + (1 - QUERY_COVERAGE_FLOOR) * title_coverage(" ".join(request), norm.split())
        )
    )


def _numbers(text: str) -> list[str]:
    return _DIGITS.findall(text)


def spelling(asked: str, title: str) -> float:
    """How alike the request and a title are letter by letter (spaces removed), 0-1: 1 when
    they're the same (4+ letters); else 0 when the request is short or their numbers differ."""
    title = title.replace(" ", "")
    if asked == title and len(title) >= EXACT_MIN_CHARS:
        return 1.0
    if len(asked) < SPELLING_MIN_CHARS or _numbers(asked) != _numbers(title):
        return 0.0
    return fuzz.ratio(asked, title) / 100


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
