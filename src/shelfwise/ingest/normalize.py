"""Normalization for catalog records: ISBNs, text, titles, author names (design doc §10)."""

import re
import unicodedata

_ISBN_CHARS = re.compile(r"[^0-9Xx]")
_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]")
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
_SERIES_SUFFIX = re.compile(r"\s*\([^)]*#\s*\d+[^)]*\)\s*$")  # Goodreads-style "(Series, #4)"
_TRAILING_DATES = re.compile(r",?\s*\b\d{3,4}\??\s*-\s*(\d{3,4}\??)?\.?\s*$")
_ARTICLES = ("the ", "a ", "an ")
_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


# --- ISBN -------------------------------------------------------------------------------------


def _isbn10_is_valid(isbn: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", isbn):
        return False
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn))
    return total % 11 == 0


def _isbn13_check_digit(first12: str) -> str:
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(first12))
    return str((10 - total % 10) % 10)


def normalize_isbn(raw: str | None) -> str | None:
    """Return a valid ISBN-13, converting ISBN-10, or None if the input is not a valid ISBN."""
    if not raw:
        return None
    isbn = _ISBN_CHARS.sub("", raw).upper()
    if len(isbn) == 10:
        if not _isbn10_is_valid(isbn):
            return None
        first12 = "978" + isbn[:9]
        return first12 + _isbn13_check_digit(first12)
    if len(isbn) == 13 and isbn.isdigit() and isbn[:3] in ("978", "979"):
        return isbn if _isbn13_check_digit(isbn[:12]) == isbn[12] else None
    return None


# --- Text and titles --------------------------------------------------------------------------


def normalize_text(raw: str) -> str:
    """Unicode NFKC and collapsed whitespace; keeps case and punctuation for display."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", raw)).strip()


def fold_text(text: str) -> str:
    """Casefolded, accent-free, punctuation-free, single-spaced: for matching, not display."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(_NON_WORD.sub(" ", without_marks).split())


def split_title(title: str, subtitle: str | None = None) -> tuple[str, str | None]:
    """Split "Sapiens: A Brief History" into title and subtitle when no subtitle is given."""
    title = normalize_text(title)
    if subtitle:
        return title, normalize_text(subtitle)
    main, sep, rest = title.partition(": ")
    return (main, rest) if sep and rest else (title, None)


def title_norm(title: str) -> str:
    """Matching key for titles: drops series suffixes, leading articles, case and punctuation."""
    folded = fold_text(_SERIES_SUFFIX.sub("", title))
    for article in _ARTICLES:
        if folded.startswith(article):
            return folded[len(article) :]
    return folded


# --- Authors ----------------------------------------------------------------------------------


def normalize_author(raw: str) -> tuple[str, str]:
    """Return (display name, matching key).

    "Tolkien, J. R. R. (John Ronald Reuel), 1892-1973" -> ("J. R. R. Tolkien", "jrr tolkien")
    """
    name = _PARENTHETICAL.sub("", normalize_text(raw))
    name = _TRAILING_DATES.sub("", name).strip(" ,")
    parts = [part.strip() for part in name.split(",")]
    suffix = ""
    if len(parts) == 3 and parts[2].casefold() in _NAME_SUFFIXES:
        *parts, suffix = parts  # "King, Martin Luther, Jr."
    if len(parts) == 2 and all(parts) and parts[1].casefold() not in _NAME_SUFFIXES:
        name = f"{parts[1]} {parts[0]}"
    if suffix:
        name = f"{name} {suffix}"
    display = _WHITESPACE.sub(" ", name).strip()

    # Join runs of single-letter initials so "J. R. R." and "J.R.R." match.
    merged: list[str] = []
    previous_was_initial = False
    for token in fold_text(display).split():
        is_initial = len(token) == 1
        if is_initial and previous_was_initial:
            merged[-1] += token
        else:
            merged.append(token)
        previous_was_initial = is_initial
    return display, " ".join(merged)
