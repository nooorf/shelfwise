"""Map messy source subjects onto a controlled genre vocabulary.

Open Library and Goodreads subjects look like "Fiction, psychological", "Detective and mystery
stories" or "New York Times bestseller". Each rule matches folded subject text; anything that
maps to no genre and isn't noise is kept as a tag, which still feeds lexical search.
"""

import re
from dataclasses import dataclass, field

from shelfwise.ingest.normalize import normalize_text

MAX_TAGS = 30


@dataclass(frozen=True)
class GenreRule:
    genre: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = field(default=())

    def matches(self, subject: str) -> bool:
        return any(re.search(p, subject) for p in self.include) and not any(
            re.search(p, subject) for p in self.exclude
        )


_NONFICTION_ONLY = (r"\bfiction\b", r"\bnovels?\b", r"criticism")

RULES: tuple[GenreRule, ...] = (
    GenreRule(
        "psychological thriller",
        (r"psychological (fiction|thriller|suspense)", r"fiction psychological"),
    ),
    GenreRule("thriller", (r"\bthrillers?\b", r"\bsuspense\b")),
    GenreRule("mystery", (r"\bmyster(y|ies)\b",)),
    GenreRule("detective", (r"\bdetectives?\b", r"private investigators", r"police procedural")),
    GenreRule("crime", (r"\bcrime\b", r"\bmurder\b", r"\bcriminals?\b"), (r"true crime",)),
    GenreRule("true crime", (r"true crime",)),
    GenreRule("horror", (r"\bhorror\b", r"ghost stories", r"\bvampires?\b", r"\bzombies?\b")),
    GenreRule("fantasy", (r"\bfantasy\b", r"\bmagic\b", r"\bdragons?\b", r"\bwizards?\b")),
    GenreRule(
        "science fiction", (r"science fiction", r"\bsci fi\b", r"space opera", r"time travel")
    ),
    GenreRule("dystopian", (r"\bdystopia",)),
    GenreRule("romance", (r"\bromance\b", r"love stories", r"\bromantic\b")),
    GenreRule(
        "historical fiction",
        # "France, history, revolution, 1789-1799, fiction" counts; literary criticism doesn't.
        (
            r"historical fiction",
            r"fiction historical",
            r"\bhistory\b.*\bfiction\b",
            r"\bfiction\b.*\bhistory\b",
        ),
        (r"criticism",),
    ),
    GenreRule("literary fiction", (r"literary fiction", r"fiction literary")),
    GenreRule("young adult", (r"young adult",)),
    GenreRule("children's", (r"\bjuvenile\b", r"\bchildren s\b"), (r"young adult",)),
    GenreRule("classics", (r"\bclassics?\b", r"classic literature")),
    GenreRule("adventure", (r"\badventure",)),
    GenreRule("humor", (r"\bhumou?r", r"\bcomedy\b")),
    GenreRule("short stories", (r"short stories",)),
    GenreRule("poetry", (r"\bpoetry\b", r"\bpoems\b")),
    GenreRule("drama", (r"\bdrama\b", r"\bplays\b")),
    GenreRule("graphic novels", (r"graphic novels?", r"\bcomics?\b", r"\bmanga\b")),
    GenreRule("gothic", (r"\bgothic\b",)),
    GenreRule("war", (r"war fiction", r"war stories", r"world war")),
    GenreRule("biography", (r"\bbiograph",), (r"autobiograph",)),
    GenreRule("memoir", (r"\bmemoirs?\b", r"autobiograph")),
    # Technical / course books. Listed before general nonfiction so they lead the genre list.
    GenreRule(
        "artificial intelligence",
        (r"artificial intelligence", r"machine learning", r"neural networks", r"deep learning"),
    ),
    GenreRule(
        "programming",
        (
            r"\bprogramming\b",
            r"program(ming)? languages?",
            r"\bpython\b",
            r"\bjava\b",
            r"\bjavascript\b",
        ),
    ),
    GenreRule(
        "computer science",
        (
            r"computer science",
            r"\balgorithms?\b",
            r"data structures",
            r"operating systems",
            r"computer networks?",
            r"\bdatabases?\b",
            r"database management",
            r"computer architecture",
            r"distributed (systems|processing)",
            r"parallel (programming|processing)",
            r"software engineering",
            r"electronic data processing",
            r"\bcomputers?\b",
        ),
    ),
    GenreRule(
        "mathematics",
        (
            r"\bmathematic",
            r"\balgebras?\b",
            r"\bcalculus\b",
            r"\bstatistics\b",
            r"\bprobabilit",
            r"\bgeometry\b",
        ),
    ),
    GenreRule("engineering", (r"\bengineering\b",)),
    GenreRule("history", (r"\bhistory\b",), _NONFICTION_ONLY),
    GenreRule(
        "science",
        (r"^science\b", r"\bphysics\b", r"\bbiology\b", r"\bastronomy\b"),
        _NONFICTION_ONLY,
    ),
    GenreRule("philosophy", (r"\bphilosoph",)),
    GenreRule("psychology", (r"\bpsychology\b",), _NONFICTION_ONLY),
    GenreRule("self-help", (r"self help", r"self improvement", r"personal development")),
    GenreRule("business", (r"\bbusiness\b", r"\beconomics\b", r"\bmanagement\b"), _NONFICTION_ONLY),
    GenreRule("politics", (r"\bpolitic",), _NONFICTION_ONLY),
    GenreRule("religion", (r"\breligio", r"\bspiritual"), _NONFICTION_ONLY),
    GenreRule("travel", (r"\btravel\b",), _NONFICTION_ONLY),
    GenreRule("essays", (r"\bessays\b",)),
)
GENRES: tuple[str, ...] = tuple(dict.fromkeys(rule.genre for rule in RULES))
NONFICTION_GENRES = frozenset(
    {
        "true crime", "biography", "memoir", "history", "science", "philosophy", "psychology",
        "self-help", "business", "politics", "religion", "travel", "essays",
        "artificial intelligence", "programming", "computer science", "mathematics", "engineering",
    }
)  # fmt: skip
_FICTION = re.compile(r"\bfiction\b|\bnovels?\b|\bstories\b")

_NOISE = (
    r"bestseller",
    r"^fiction( general)?$",
    r"^fiction \w+ general$",
    r"^(nyt|award|accessible book|protected daisy|in library|large type|reading level)",
    r"^open library",
    r"\d{4}",
)


def _fold_subject(subject: str) -> str:
    return " ".join(re.sub(r"[^\w\s]|_", " ", normalize_text(subject).casefold()).split())


# Signals that a book is used for teaching; normalized to one searchable tag.
_TEXTBOOK_SUBJECTS = {"open syllabus project", "textbooks", "textbook"}


def _as_tag(folded: str) -> str:
    # "Marriage, fiction" / "Artists -- Fiction" -> "marriage" / "artists"
    if folded in _TEXTBOOK_SUBJECTS:
        return "textbook"
    return re.sub(r"\s+fiction$", "", folded).strip()


def map_subjects(subjects: list[str]) -> tuple[list[str], list[str]]:
    """Return (genres in vocabulary order, up to MAX_TAGS leftover tags).

    Sources tag novels with bare subjects like "History" or "Psychology", so once any subject
    marks the work as fiction, nonfiction-only genres are dropped for the whole work.
    """
    genres: set[str] = set()
    tags: list[str] = []
    is_fiction = False
    for subject in subjects:
        folded = _fold_subject(subject)
        if not folded:
            continue
        is_fiction = is_fiction or (bool(_FICTION.search(folded)) and "true crime" not in folded)
        matched = {rule.genre for rule in RULES if rule.matches(folded)}
        genres |= matched
        if matched or any(re.search(p, folded) for p in _NOISE) or len(folded) > 40:
            continue
        tag = _as_tag(folded)
        if tag and tag not in tags:
            tags.append(tag)
    if is_fiction:
        genres -= NONFICTION_GENRES
    return [g for g in GENRES if g in genres], tags[:MAX_TAGS]
