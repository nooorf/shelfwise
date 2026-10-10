"""Checks on everything the LLM writes before anyone sees it (design doc §19.1, step 3).

| Check            | Rule                                                                        |
| ---------------- | --------------------------------------------------------------------------- |
| other books      | no catalog title or author outside the books shown (and the reader's seeds) |
| missing books    | never a title or author the reader named that the library doesn't have      |
| availability     | never: the cards show it from the copy table, live                          |
| numbers          | every number must appear in the record (pages, year, description)           |
| claims           | awards, bestseller status, adaptations, "acclaimed": only if the record says |
| meta             | no "tags", "records": the reader sees books, not data                       |

Titles are matched as word sequences over the catalog's title and author dictionary. A title of
one word after its article ("The Road", "Beloved") is skipped: as a phrase it is ordinary English,
and flagging it would throw away good sentences far more often than it would catch a wrong book.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence

from rapidfuzz import fuzz, process
from sqlalchemy import Connection, text

from shelfwise.generation.context import Candidate
from shelfwise.ingest.normalize import fold_text

MAX_PHRASE = 8  # words; longer titles are still caught by their first eight words
CLOSE_SPELLING = 88  # rapidfuzz ratio: "frankenstien", "to kill a mocking bird" are owned
_ARTICLES = ("the ", "a ", "an ")
_AVAILABILITY = re.compile(
    r"\b(?:available|availability|unavailable|on the shelf|on loan|checked out|in stock|due back"
    r"|can (?:borrow|check (?:it )?out|take (?:it )?home)|ready to borrow|place a hold)\b"
)
_CLAIMS = re.compile(
    r"\b(?:awards?|award winning|prize|pulitzer|booker|nobel|hugo|nebula|bestsell\w*|best sell\w*"
    r"|million copies|adapted|adaptation|film|movie|tv|television|netflix|hbo|acclaimed"
    r"|beloved by millions|cult classic)\b"
)
# "the third book in the X trilogy", "X book 4": the name is X.
_SERIES_LEAD = re.compile(
    r"^(?:the )?(?:(?:first|second|third|fourth|fifth|next|new|last|latest|\d+\w*) )?"
    r"(?:book|novel|sequel|prequel|part|volume|one) (?:in|of|to) "
)
_SERIES_TAIL = re.compile(r" (?:trilogy|series|saga|books?(?: \d+)?|vol(?:ume)? \d+|part \d+|\d+)$")
_SUBTITLE = re.compile(r"\s*(?::|\s-\s|\(|—)")  # "Title: A Novel", "Title (Series, #1)"
_NUMBER = re.compile(r"\b\d[\d,]*\b")
# The machinery showing through ("the tags show no violence"): the reader never sees tags.
_META = re.compile(r"\b(?:tags?|tagged|records?|matches field|the data)\b")


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]  # fmt: skip
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _pair(n: int) -> str:
    return _ONES[n] if n < 20 else f"{_TENS[n // 10]} {_ONES[n % 10]}".strip()


def year_words(text: str) -> str | None:
    """A title that is a year, as words: "1984" -> "nineteen eighty four" (the catalog spells
    out "Nineteen Eighty-Four"). Years 1010-1999 with no zero tens ("1905" is left alone)."""
    if not re.fullmatch(r"1[0-9][1-9][0-9]", text):
        return None
    return f"{_pair(int(text[:2]))} {_pair(int(text[2:]))}"


def _strip_article(folded: str) -> str:
    for article in _ARTICLES:
        if folded.startswith(article):
            return folded[len(article) :]
    return folded


def _key(name: str) -> str | None:
    folded = _strip_article(fold_text(name))
    return folded if len(folded.split()) >= 2 else None


def missing_key(name: str) -> str | None:
    """How a name the library doesn't have is spotted in text: folded, without series words
    or a leading article; None when that leaves one word (too common to look for)."""
    folded = _SERIES_TAIL.sub("", _SERIES_LEAD.sub("", fold_text(name)))
    return _key(folded)


class CatalogNames:
    """The catalog's titles and author names, for spotting books the LLM wasn't given."""

    def __init__(
        self, titles: dict[str, set[int]], authors: dict[str, set[int]],
        short: set[str] | None = None,
    ) -> None:  # fmt: skip
        self.titles = titles
        self.authors = authors
        self.short = short or set()  # one-word titles ("dune", "1984"): never scanned for
        self._spellings: list[str] | None = None

    @classmethod
    def from_pairs(
        cls, titles: Iterable[tuple[int, str]], authors: Iterable[tuple[int, str]]
    ) -> "CatalogNames":
        by_title: dict[str, set[int]] = defaultdict(set)
        by_author: dict[str, set[int]] = defaultdict(set)
        short: set[str] = set()
        for work_id, title in titles:
            if key := _key(title):
                by_title[key].add(work_id)
            elif folded := _strip_article(fold_text(title)):
                short.add(folded)
            main = _strip_article(fold_text(_SUBTITLE.split(title, maxsplit=1)[0]))
            if main and len(main.split()) == 1:
                short.add(main)  # "Seabiscuit: An American Legend" is "seabiscuit" too
        for work_id, name in authors:
            if key := _key(name):
                by_author[key].add(work_id)
        return cls(dict(by_title), dict(by_author), short)

    @classmethod
    def load(cls, conn: Connection) -> "CatalogNames":
        titles = [
            (r.work_id, r.title) for r in conn.execute(text("SELECT work_id, title FROM work"))
        ]
        authors = [
            (r.work_id, r.display)
            for r in conn.execute(
                text(
                    "SELECT wa.work_id, a.display FROM work_author wa JOIN author a USING (author_id)"
                )
            )
        ]
        return cls.from_pairs(titles, authors)

    def has(self, name: str) -> bool:
        """Whether the catalog has something the reader may have meant by `name`: a title or
        author inside it ("harlan coben thrillers", "atomic habits james clear"), or one
        spelled nearly the same ("frankenstien"). The narrow sense of "not found" a reply can
        say out loud."""
        if self.mentions(name):
            return True
        if self._spellings is None:
            mains = {
                _strip_article(fold_text(_SUBTITLE.split(t, maxsplit=1)[0])) for t in self.titles
            }
            self._spellings = [*self.titles, *mains, *self.authors, *self.short]
        key = _strip_article(fold_text(name))
        if key in self.short or (year_words(key) or key) in self.titles:
            return True
        found = process.extractOne(
            key, self._spellings, scorer=fuzz.ratio, score_cutoff=CLOSE_SPELLING
        )
        return found is not None

    def mentions(self, words: str) -> list[tuple[str, str, set[int]]]:
        """("title" | "author", phrase, its works) for every catalog name in `words`."""
        tokens = fold_text(words).split()
        found = []
        for n in range(2, MAX_PHRASE + 1):
            for i in range(len(tokens) - n + 1):
                phrase = " ".join(tokens[i : i + n])
                if phrase in self.titles:
                    found.append(("title", phrase, self.titles[phrase]))
                if phrase in self.authors:
                    found.append(("author", phrase, self.authors[phrase]))
        return found


def check(
    words: str,
    records: list[Candidate],
    allowed_ids: set[int],
    names: CatalogNames,
    reader: str = "",
    missing: Sequence[str] = (),
) -> list[str]:
    """What's wrong with one piece of generated text; [] when it may be shown.

    `records` are the books it may draw facts from (one for a book's own reason, all of them
    for the intro); `allowed_ids` the books it may name; `reader` what the reader said and
    wants (echoing their "under 300 pages" or "like the hunger games" is not inventing);
    `missing` titles and authors the reader named that the library doesn't have: echoing those
    ("if you loved X...") presents them as real, so they are never allowed."""
    problems = []
    reader = fold_text(reader)
    for kind, phrase, works in names.mentions(words):
        if not works & allowed_ids and f" {phrase} " not in f" {reader} ":
            problems.append(f"names a {kind} that wasn't given: {phrase!r}")
    folded = fold_text(words)
    for name in missing:
        if (key := missing_key(name)) and f" {key} " in f" {folded} ":
            problems.append(f"names a book the library doesn't have: {key!r}")
    if match := _AVAILABILITY.search(folded):
        problems.append(f"talks about availability: {match.group(0)!r}")
    if match := _META.search(folded):
        problems.append(f"talks about the data, not the book: {match.group(0)!r}")
    record_text = fold_text(" ".join(r.record_text for r in records)) + " " + reader
    known_numbers = {n.replace(",", "") for n in _NUMBER.findall(record_text)}
    for number in _NUMBER.findall(words):
        if number.replace(",", "") not in known_numbers:
            problems.append(f"a number not in the record: {number}")
    for match in _CLAIMS.finditer(folded):
        stem = match.group(0)[:6]
        if stem not in record_text:
            problems.append(f"a claim the record doesn't make: {match.group(0)!r}")
    return problems
