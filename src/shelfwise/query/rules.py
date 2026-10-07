"""Deterministic first pass of query understanding (design doc §12.2, step 2).

Rules handle what an LLM gets wrong and regexes get right: page counts, years, decades, relative
dates, availability phrases and ISBNs. Each match becomes a `Constraint` with the words it came
from, and is blanked out so no phrase is counted twice. What's left is the *residual*: the
request's meaning without its filters ("mystery under 300 pages after 2015" -> "mystery").

Strength defaults (§12.4): explicit numbers are hard; vague size or recency words ("short",
"recent") are soft; a nearby hedge ("ideally", "if possible") makes anything soft.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from shelfwise.ingest.normalize import normalize_text
from shelfwise.query.constraints import Constraint, Op, Strength
from shelfwise.query.numbers import NUMBER_PHRASE, words_to_number
from shelfwise.retrieval.lookup import isbns_in

SHORT_BOOK_PAGES = 250
LONG_BOOK_PAGES = 450
RECENT_YEARS = 5

_PAGES = r"\s*-?\s*(?:pages?|pgs?|pp)\b"
_N = r"(?P<n>\d{1,4})"
_YEAR = r"(?P<y>1[5-9]\d\d|20\d\d)"
_PUBLISHED = r"(?:(?:published|written|released|came out|that came out|printed)\s+)?"
# "about"/"around" are not hedges in general ("a book about grief"); they only soften a page count,
# which the bare-pages rule handles.
_HEDGE = re.compile(
    r"\b(ideally|preferably|if possible|maybe|hopefully|would be nice|nice to have|"
    r"not necessarily|doesn'?t have to be|does not have to be)\b"
)
# "set in the 1920s" describes the story, not when the book was published.
_SETTING = re.compile(r"\b(set|takes? place|taking place|happens|happening)\s+(in|during)\b")
_NOT_REALLY = re.compile(
    r"\b(don'?t|do not|doesn'?t|does not)\s+(care|mind|matter)\s+(if|whether)\b|"
    r"\b(even if|regardless of|whether or not)\b"
)
# "The twenties" is left out: in 2026 it's as likely to mean the 2020s as the 1920s.
_DECADE_WORDS = {
    "thirties": 1930, "forties": 1940, "fifties": 1950, "sixties": 1960, "seventies": 1970,
    "eighties": 1980, "nineties": 1990,
}  # fmt: skip
_SMALL_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "few": 5, "couple": 2}
_CONNECTORS = {
    "and", "or", "but", "with", "that", "which", "is", "are", "was", "published", "written",
    "released", "from", "in", "of", "the", "a", "an", "under", "over", "by",
}  # fmt: skip


@dataclass
class RuleParse:
    text: str  # normalized, lowercased input with number words converted
    constraints: list[Constraint] = field(default_factory=list)
    residual: str = ""


@dataclass
class _Parser:
    text: str
    today: date
    constraints: list[Constraint] = field(default_factory=list)
    _masked: str = ""

    def __post_init__(self) -> None:
        self._masked = self.text

    def _hedged(self, start: int, end: int) -> bool:
        window = self.text[max(0, start - 30) : end + 15]
        return bool(_HEDGE.search(window))

    def _consume(self, start: int, end: int) -> None:
        self._masked = self._masked[:start] + " " * (end - start) + self._masked[end:]

    def add(
        self,
        match: re.Match[str],
        field_name: str,
        op: Op,
        value: object,
        strength: Strength = "hard",
    ) -> None:
        start, end = match.span()
        if self._hedged(start, end):
            strength = "soft"
        self.constraints.append(
            Constraint(
                field=field_name,
                op=op,
                value=value,
                strength=strength,
                source="rule",
                span=self.text[start:end].strip(),
            )
        )
        self._consume(start, end)

    def add_range(self, match: re.Match[str], field_name: str, low: int, high: int) -> None:
        self.add(match, field_name, "gte", low)
        self.constraints.append(
            self.constraints[-1].model_copy(update={"op": "lte", "value": high})
        )

    def each(self, pattern: str, handle: Callable[[re.Match[str]], None]) -> None:
        for match in list(re.finditer(pattern, self._masked)):
            if self._masked[match.start() : match.end()].strip():  # not consumed meanwhile
                handle(match)

    def residual(self) -> str:
        words = re.sub(r"[\s,;]+", " ", self._masked).strip(" ,.?!").split()
        while words and words[-1].strip(",.?!") in _CONNECTORS:
            words.pop()
        while words and words[0].strip(",.?!") in _CONNECTORS:
            words.pop(0)
        return " ".join(words).strip(" ,.?!")


def _convert_number_words(text: str) -> str:
    """'under three hundred pages' -> 'under 300 pages'. Only right before a page unit, so titles
    like "Nineteen Eighty-Four" are left alone."""

    def replace(match: re.Match[str]) -> str:
        number = words_to_number(match.group("num"))
        return match.group(0) if number is None else f"{number}{match.group('unit')}"

    return re.sub(rf"(?P<num>{NUMBER_PHRASE.pattern})(?P<unit>{_PAGES})", replace, text)


def _pages(p: _Parser) -> None:
    upper: dict[str, Op] = {"under": "lt", "less than": "lt", "fewer than": "lt", "below": "lt",
             "shorter than": "lt", "at most": "lte", "no more than": "lte", "not more than": "lte",
             "up to": "lte", "max": "lte", "maximum": "lte", "maximum of": "lte", "within": "lte"}  # fmt: skip
    lower: dict[str, Op] = {"over": "gt", "more than": "gt", "longer than": "gt", "above": "gt",
             "at least": "gte", "minimum": "gte", "minimum of": "gte"}  # fmt: skip
    p.each(
        rf"\bbetween\s+(?P<a>\d{{1,4}})\s*(?:and|to|-)\s*(?P<b>\d{{1,4}}){_PAGES}",
        lambda m: p.add_range(m, "pages", int(m["a"]), int(m["b"])),
    )

    def page_bound(op: Op) -> Callable[[re.Match[str]], None]:
        return lambda m: p.add(m, "pages", op, int(m["n"]))

    page_ops: dict[str, Op] = {**upper, **lower}
    for words, op in page_ops.items():
        p.each(rf"\b{words}\s+{_N}{_PAGES}", page_bound(op))
    p.each(rf"[<]\s*{_N}{_PAGES}", lambda m: p.add(m, "pages", "lt", int(m["n"])))
    p.each(rf"[>]\s*{_N}{_PAGES}", lambda m: p.add(m, "pages", "gt", int(m["n"])))
    p.each(
        rf"\b{_N}{_PAGES}\s+or\s+(?:less|fewer|under)\b",
        lambda m: p.add(m, "pages", "lte", int(m["n"])),
    )
    p.each(
        rf"\b{_N}{_PAGES}\s+or\s+(?:more|longer|over)\b",
        lambda m: p.add(m, "pages", "gte", int(m["n"])),
    )
    # A bare number of pages ("a 100 page novel") is a target, not a limit.
    p.each(rf"\b(?:around|about|roughly|approximately|~)?\s*{_N}{_PAGES}",
           lambda m: p.add(m, "pages", "approx", int(m["n"]), "soft"))  # fmt: skip
    short = (
        r"\b(?:not too long|not very long|not that long|quick read|light read|novella|"
        r"(?:(?:that|which) )?(?:i |you )?(?:can |could )?(?:finish|read)(?: it)? in (?:a|one) (?:weekend|day|sitting|evening)|"
        r"short(?!\s+stor))\b"
    )
    p.each(short, lambda m: p.add(m, "pages", "lte", SHORT_BOOK_PAGES, "soft"))
    p.each(
        # "epic fantasy" and "epic poetry" are kinds of book, not lengths.
        r"\b(?:epic(?!\s+(?:fantasy|poems?|poetry))|doorstopper|chunky|thick|long(?!\s+(?:ago|time)))\b",
        lambda m: p.add(m, "pages", "gte", LONG_BOOK_PAGES, "soft"),
    )


def _years(p: _Parser) -> None:
    def unless_setting(handle: Callable[[re.Match[str]], None]) -> Callable[[re.Match[str]], None]:
        # "set in the 1920s" describes the story, not when it was published.
        def guarded(m: re.Match[str]) -> None:
            # The match may itself start with "in the", so look across it, not just before it.
            if not _SETTING.search(p.text[max(0, m.start() - 30) : m.end()]):
                handle(m)

        return guarded

    year = int
    p.each(
        rf"\b{_PUBLISHED}between\s+(?P<a>1[5-9]\d\d|20\d\d)\s*(?:and|to|-)\s*(?P<b>1[5-9]\d\d|20\d\d)\b",
        lambda m: p.add_range(m, "year", year(m["a"]), year(m["b"])),
    )
    p.each(
        rf"\b{_PUBLISHED}(?:from\s+)?{_YEAR}\s+(?:on|onwards?|forward|and later|or later|and newer|or newer)\b",
        lambda m: p.add(m, "year", "gte", year(m["y"])),
    )
    year_ops: dict[str, Op] = {
        "after": "gt", "later than": "gt", "newer than": "gt", "post": "gt", "since": "gte",
        "before": "lt", "prior to": "lt", "earlier than": "lt", "older than": "lt", "pre": "lt",
    }  # fmt: skip

    def year_bound(op: Op) -> Callable[[re.Match[str]], None]:
        return lambda m: p.add(m, "year", op, year(m["y"]))

    for words, op in year_ops.items():
        p.each(rf"\b{_PUBLISHED}{words}[\s-]+{_YEAR}\b(?!s)", year_bound(op))
    p.each(
        rf"\b(?:published|written|released|came out|printed)\s+in\s+(?:the\s+year\s+)?{_YEAR}\b(?!s)",
        lambda m: p.add(m, "year", "eq", year(m["y"])),
    )
    p.each(
        rf"\bfrom\s+{_YEAR}\b(?!s)", unless_setting(lambda m: p.add(m, "year", "eq", year(m["y"])))
    )

    def decade(m: re.Match[str]) -> None:
        start = (
            int(m["d"]) if len(m["d"]) == 4 else (1900 if int(m["d"]) >= 30 else 2000) + int(m["d"])
        )
        # "the 1800s" is a century; "the 2000s" is usually read as the decade.
        p.add_range(m, "year", start, start + (99 if start % 100 == 0 and start < 2000 else 9))

    def century(m: re.Match[str]) -> None:
        start = (int(m["c"]) - 1) * 100  # the 19th century -> 1800-1899, like "the 1800s"
        p.add_range(m, "year", start, start + 99)

    p.each(
        rf"\b{_PUBLISHED}(?:from |in |of )?(?:the\s+)?(?P<d>(?:1[5-9]|20)\d0)'?s\b",
        unless_setting(decade),
    )
    p.each(rf"\b{_PUBLISHED}(?:from |in |of )?the\s+'?(?P<d>[0-9]0)'?s\b", unless_setting(decade))
    p.each(
        rf"\b{_PUBLISHED}(?:from |in |of )?the\s+(?P<c>1[6-9]|2[01])(?:th|st)[\s-]+century\b",
        unless_setting(century),
    )
    p.each(
        rf"\b{_PUBLISHED}(?:from |in |of )?(?:the\s+)?(?P<w>{'|'.join(_DECADE_WORDS)})\b",
        unless_setting(
            lambda m: p.add_range(m, "year", _DECADE_WORDS[m["w"]], _DECADE_WORDS[m["w"]] + 9)
        ),
    )

    def last_n_years(m: re.Match[str]) -> None:
        n = int(m["n"]) if m["n"].isdigit() else _SMALL_NUMBERS[m["n"]]
        p.add(m, "year", "gte", p.today.year - n)

    p.each(
        rf"\b{_PUBLISHED}(?:in|from|within|over|during)?\s*(?:the\s+)?(?:last|past)\s+"
        rf"(?:a\s+)?(?P<n>\d{{1,2}}|{'|'.join(_SMALL_NUMBERS)})\s+years?\b",
        last_n_years,
    )
    p.each(
        rf"\b{_PUBLISHED}(?:in|from|within|over|during)?\s*(?:the\s+)?(?:last|past)\s+decade\b",
        lambda m: p.add(m, "year", "gte", p.today.year - 10),
    )
    p.each(rf"\b{_PUBLISHED}this\s+year\b", lambda m: p.add(m, "year", "gte", p.today.year))
    p.each(
        r"\b(?:(?:comes|coming|is) out\s+)?next\s+year\b",
        lambda m: p.add(m, "year", "eq", p.today.year + 1),
    )
    p.each(
        r"\b(?:recently published|(?:published|released|written) recently|recent|new releases?|"
        r"newly published|latest|brand new|just came out|came out recently)\b",
        lambda m: p.add(m, "year", "gte", p.today.year - RECENT_YEARS, "soft"),
    )


def _availability(p: _Parser) -> None:
    phrases = (
        r"\b(?:available(?:\s+(?:now|today|right now|to borrow|for checkout))?|in stock|"
        r"on the shel(?:f|ves)|not checked out|"
        r"(?:(?:that|which)\s+)?(?:i\s+)?(?:can|could)\s+(?:i\s+)?(?:take|borrow|check out|get|grab)"
        r"(?:\s+\w+){0,3}?\s+"
        r"(?:home\s+)?(?:today|now|right now|tonight)|"
        r"take (?:it )?home (?:today|now|tonight)|borrow (?:today|now|right now)|"
        # "is anything by king in right now", "whatever is in" (at the end of the message)
        r"in (?:right now|now|today|at the moment)(?!['\u2019])|"
        r"(?:whatever|what|anything that|that|which)(?:['\u2019]s| is| are) in(?=\W*$))\b"
    )

    def handle(m: re.Match[str]) -> None:
        if _SETTING.search(p.text[max(0, m.start() - 20) : m.end()]):
            return  # "set in today's london" describes the story
        if _NOT_REALLY.search(p.text[max(0, m.start() - 40) : m.start()]):
            p._consume(*m.span())
            return
        p.add(m, "available_now", "eq", True)

    p.each(phrases, handle)


def _isbns(p: _Parser) -> None:
    isbns = isbns_in(p.text)
    if isbns:
        p.constraints.append(
            Constraint(field="isbn", op="in", value=isbns, strength="hard", source="rule")
        )
        for match in re.finditer(r"[\dXx-]{10,17}", p._masked):
            if isbns_in(match.group(0)):
                p._consume(*match.span())


def _tidy(constraints: list[Constraint]) -> list[Constraint]:
    """Drop exact duplicates, and soft constraints on a field that already has a hard one
    ("a short horror book under 250 pages": the explicit limit wins)."""
    hard_fields = {c.field for c in constraints if c.strength == "hard"}
    seen: set[tuple[str, str, str, str]] = set()
    kept = []
    for c in constraints:
        key = (c.field, c.op, repr(c.value), c.strength)
        if key in seen or (c.strength == "soft" and c.field in hard_fields):
            continue
        seen.add(key)
        kept.append(c)
    return kept


def parse_rules(query: str, today: date | None = None) -> RuleParse:
    text = _convert_number_words(normalize_text(query).lower())
    parser = _Parser(text=text, today=today or date.today())
    for rule in (_isbns, _pages, _years, _availability):
        rule(parser)
    return RuleParse(text=text, constraints=_tidy(parser.constraints), residual=parser.residual())
