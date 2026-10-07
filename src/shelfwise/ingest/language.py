"""Keep the catalog English (design decision 2026-10-06: English only).

Source language codes aren't enough: Goodreads and Open Library both label some books "eng" whose
blurb is in Portuguese or German, or that are a French edition. A book counts as non-English when:

- its description is detected as another language (langdetect, seeded so results are stable),
- its title is mostly in a non-Latin script, or
- one of its ISBNs is on the hand-kept list in data/seed/excluded_isbns.csv: foreign-language
  editions whose blurb happens to be English ("Anges et Demons"), which no detector can see.

English editions with foreign titles ("Les Misérables") stay.
"""

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path

from langdetect import DetectorFactory, LangDetectException, detect_langs
from sqlalchemy import Connection, text

DetectorFactory.seed = 0  # langdetect is randomized; a seed makes it repeatable

EXCLUDED = Path("data/seed/excluded_isbns.csv")
MIN_WORDS = 8  # shorter texts are too ambiguous to judge
MIN_ENGLISH = 0.5  # langdetect's probability for English
MAX_NON_LATIN = 0.5  # share of a title's letters outside Latin scripts


def description_language(description: str | None) -> str | None:
    """The detected language code when it isn't English, else None (English, or too short)."""
    if not description or len(description.split()) < MIN_WORDS:
        return None
    try:
        languages = detect_langs(description)
    except LangDetectException:
        return None
    english = next((lang.prob for lang in languages if lang.lang == "en"), 0.0)
    return None if english >= MIN_ENGLISH else languages[0].lang


def non_latin_share(value: str) -> float:
    letters = [ch for ch in value if ch.isalpha()]
    return sum(ord(ch) > 0x24F for ch in letters) / len(letters) if letters else 0.0


def load_excluded(path: Path = EXCLUDED) -> dict[str, str]:
    """{isbn13: reason} from the hand-kept exclusion list."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {row["isbn13"].strip(): row["reason"].strip() for row in csv.DictReader(f)}


def non_english_reason(
    title: str,
    description: str | None,
    isbns: Iterable[str] = (),
    excluded: Mapping[str, str] | None = None,
) -> str | None:
    """Why a book is not English, or None if it is (or can't be told apart from English)."""
    for isbn in isbns:
        if excluded and isbn in excluded:
            return f"excluded edition: {excluded[isbn]}"
    if non_latin_share(title) > MAX_NON_LATIN:
        return "title in a non-Latin script"
    if language := description_language(description):
        return f"description in {language!r}"
    return None


_WORKS_SQL = text(
    """
    SELECT w.work_id, w.title, w.description,
           coalesce(array_agg(e.isbn13) FILTER (WHERE e.isbn13 IS NOT NULL), '{}') AS isbns
    FROM work w LEFT JOIN edition e USING (work_id)
    GROUP BY w.work_id
    ORDER BY w.work_id
    """
)


def find_non_english(
    conn: Connection, excluded: Mapping[str, str] | None = None
) -> list[tuple[int, str, str]]:
    """(work_id, title, reason) for every non-English work in the catalog."""
    found = []
    for r in conn.execute(_WORKS_SQL):
        if reason := non_english_reason(r.title, r.description, r.isbns, excluded):
            found.append((r.work_id, r.title, reason))
    return found
