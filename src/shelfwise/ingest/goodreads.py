"""Read the UCSD Book Graph (Goodreads, 2017) genre subsets into edition records.

Mengting Wan & Julian McAuley, "Item Recommendation on Monotonic Behavior Chains" (RecSys 2018).
Academic use only: the raw files stay in data/raw/ (git-ignored) and are never redistributed.

Each subset is a gzipped JSON-lines file of editions. A book is kept only if it is in English, has
a valid ISBN, a page count and a real description, and isn't an audiobook. Goodreads has no
subjects; readers' shelves ("psychological-thriller", "ya", "to-read") are the closest thing, so
the most-used meaningful shelves become subjects for the genre mapper.
"""

import gzip
import html
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from shelfwise.ingest.normalize import normalize_isbn
from shelfwise.ingest.records import MAX_PAGES, MIN_PAGES, EditionRecord

BASE_URL = "https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads"

# Share of the imported catalog per genre subset (sums to 1).
SUBSETS: dict[str, float] = {
    "mystery_thriller_crime": 0.18,
    "fantasy_paranormal": 0.17,
    "history_biography": 0.17,
    "romance": 0.15,
    "young_adult": 0.12,
    "children": 0.10,
    "comics_graphic": 0.07,
    "poetry": 0.04,
}

ENGLISH = frozenset({"eng", "en", "en-US", "en-GB", "en-CA"})
MIN_DESCRIPTION_CHARS = 150
MAX_AUTHORS = 3
MAX_SHELVES = 15
SHELF_SHARE = 0.2  # keep shelves used at least this often relative to the top meaningful shelf

# Shelves about the reader, not the book.
_META_SHELF = re.compile(
    r"^(to-?read|currently-?reading|read|re-?read|tbr|favou?rites?|fav|owned|own|i-own|"
    r"books-i-own|owned-books|my-books|my-library|library|library-books?|home-library|"
    r"kindle|nook|e-?books?|audio-?books?|audible|audio|wish-?list|wishlist|to-buy|default|"
    r"dnf|did-not-finish|abandoned|gave-up|unfinished|on-hold|maybe|borrowed|book-club|"
    r"bookclub|series|calibre|shelfari-.*|.*\d{4}.*|.*-read|read-.*|have|books|novels?)$"
)
# Reader shorthand -> words the genre mapper understands.
_SHELF_ALIASES = {
    "ya": "young adult",
    "ya-fiction": "young adult fiction",
    "childrens": "children's",
    "children-s": "children's",
    "children-s-books": "children's",
    "childrens-books": "children's",
    "children-books": "children's",
    "kids": "children's",
    "kids-books": "children's",
    "middle-grade": "children's",
    "picture-books": "children's",
    "picture-book": "children's",
    "non-fiction": "nonfiction",
}
_AUDIO_FORMAT = re.compile(r"audio|\bcd\b|mp3", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
# "The Hunger Games (The Hunger Games, #1)", "Plague (Gone #4)": the dataset's
# title_without_series often still has it.
_SERIES_SUFFIX = re.compile(r"\s*\([^()]*#\s*\d[\d.-]*\)\s*$")


def file_name(subset: str) -> str:
    return f"goodreads_books_{subset}.json.gz"


def iter_json_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def _int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def clean_description(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(_TAG.sub(" ", text))
    text = " ".join(text.split())
    return text or None


def strip_series(title: str) -> str:
    return _SERIES_SUFFIX.sub("", title).strip() or title.strip()


def shelves_to_subjects(shelves: Sequence[Mapping[str, str]]) -> list[str]:
    """The most-used shelves that describe the book, as subject strings."""
    meaningful = [
        (count, s["name"].lower())
        for s in shelves
        if (count := _int(s.get("count"))) and not _META_SHELF.match(s["name"].lower())
    ]
    if not meaningful:
        return []
    meaningful.sort(reverse=True)
    floor = meaningful[0][0] * SHELF_SHARE
    names = [name for count, name in meaningful if count >= floor][:MAX_SHELVES]
    return list(dict.fromkeys(_SHELF_ALIASES.get(n, n.replace("-", " ")) for n in names))


def rejection(book: Mapping[str, Any]) -> str | None:
    """Why a raw Goodreads edition can't be used, or None if it can."""
    if book.get("language_code") not in ENGLISH:
        return "not English"
    if (
        normalize_isbn(book.get("isbn13") or "") is None
        and normalize_isbn(book.get("isbn") or "") is None
    ):
        return "no valid ISBN"
    pages = _int(book.get("num_pages"))
    if pages is None or not MIN_PAGES <= pages <= MAX_PAGES:
        return "no page count"
    if _AUDIO_FORMAT.search(book.get("format") or ""):
        return "audiobook"
    if len(clean_description(book.get("description")) or "") < MIN_DESCRIPTION_CHARS:
        return "no description"
    if not any(not a.get("role") for a in book.get("authors") or []):
        return "no author"
    return None


def to_record(
    book: Mapping[str, Any], author_names: Mapping[str, str], first_pub_year: int | None
) -> EditionRecord | None:
    """A usable edition (rejection() is None) as an EditionRecord; None if its author is unknown."""
    authors = [
        name
        for a in book["authors"]
        if not a.get("role") and (name := author_names.get(a["author_id"]))
    ][:MAX_AUTHORS]
    isbn13 = normalize_isbn(book.get("isbn13") or "") or normalize_isbn(book.get("isbn") or "")
    if not authors or isbn13 is None:
        return None
    pub_year = _int(book.get("publication_year"))
    return EditionRecord(
        isbn13=isbn13,
        title=strip_series(book.get("title_without_series") or book["title"]),
        authors=authors,
        publisher=(book.get("publisher") or "").strip() or None,
        pub_year=pub_year,
        first_pub_year=first_pub_year,
        pages=_int(book.get("num_pages")),
        language="en",
        format=(book.get("format") or "").strip() or None,
        description=clean_description(book.get("description")),
        subjects=[
            s
            for s in shelves_to_subjects(book.get("popular_shelves") or [])
            if s not in {a.casefold() for a in authors}  # "dan brown" is a shelf, not a topic
        ],
        source_work_key=f"goodreads:{book['work_id']}",
    )


def quotas(total: int, subsets: Mapping[str, float] = SUBSETS) -> dict[str, int]:
    """Split `total` books across subsets by share; rounding leftovers go to the largest shares."""
    counts = {s: int(total * share) for s, share in subsets.items()}
    for s in sorted(subsets, key=lambda s: -subsets[s])[: total - sum(counts.values())]:
        counts[s] += 1
    return counts
