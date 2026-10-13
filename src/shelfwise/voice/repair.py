"""Names in a transcript put back to the catalog's spelling.

Whisper hears names it doesn't know as ordinary words: "Gillian Flynn" comes out "jillian
flynn", "Stephen King" as "steven king". Before the transcript is parsed, 2-4 word phrases
are compared with the catalog's author names (and titles of 3+ words), and close matches take
the catalog spelling. Two-word titles are left alone: "the girl" is close to *The Girls*, and
Whisper gets ordinary words right; it's the proper names it misspells.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy import Connection, text

from shelfwise.ingest.normalize import fold_text

AUTHOR_SCORE = 85.0  # rapidfuzz ratio, 0-100: "steven king" / "stephen king" is 87
TITLE_SCORE = 90.0
MAX_WORDS = 4
# A phrase starting or ending in one of these only matches a name that has the same word there:
# "to machine learning" is not *Python Machine Learning*; "the way of kinks" is *The Way of Kings*.
_FILLER = frozenset(
    ["a", "an", "the", "to", "of", "by", "in", "on", "for", "and", "or", "about", "like", "with", "from", "at", "is", "me", "my", "some", "any", "books", "book"]
)  # fmt: skip


@dataclass(frozen=True)
class Fix:
    heard: str
    catalog: str


class NameRepair:
    def __init__(self, authors: Iterable[str], titles: Iterable[str]) -> None:
        # By word count, folded spelling -> display spelling (and the score it needs).
        self._names: dict[int, dict[str, tuple[str, float]]] = {}
        for names, min_words, score in ((titles, 3, TITLE_SCORE), (authors, 2, AUTHOR_SCORE)):
            for display in names:
                key = fold_text(display)
                n = len(key.split())
                if min_words <= n <= MAX_WORDS:
                    self._names.setdefault(n, {})[key] = (display, score)  # authors win ties

    @classmethod
    def load(cls, conn: Connection) -> "NameRepair":
        authors = conn.execute(text("SELECT display FROM author")).scalars()
        titles = conn.execute(text("SELECT title FROM work")).scalars()
        return cls(authors, titles)

    def repair(self, transcript: str) -> tuple[str, list[Fix]]:
        """The transcript with near-miss names respelled, and what changed."""
        words = transcript.split()
        folded = [fold_text(w) for w in words]
        taken = [False] * len(words)
        fixes: dict[int, tuple[int, str, Fix]] = {}  # start -> (end, replacement, fix)
        for n in range(MAX_WORDS, 1, -1):
            names = self._names.get(n)
            if not names:
                continue
            for i in range(len(words) - n + 1):
                if any(taken[i : i + n]) or not all(folded[i : i + n]):
                    continue
                phrase = " ".join(folded[i : i + n])
                if phrase in names:
                    taken[i : i + n] = [True] * n  # already right: keep it, don't match inside
                    continue
                found = process.extractOne(phrase, names.keys(), scorer=fuzz.ratio)
                if found is None:
                    continue
                key, score, _ = found
                display, needed = names[key]
                if score < needed or not _edges_agree(folded[i : i + n], key.split()):
                    continue
                heard = " ".join(words[i : i + n])
                trailing = heard[len(heard.rstrip(".,!?;:")) :]  # keep "flynn?"'s question mark
                fixes[i] = (i + n, display + trailing, Fix(heard.rstrip(".,!?;:"), display))
                taken[i : i + n] = [True] * n
        out, i = [], 0
        while i < len(words):
            if i in fixes:
                end, replacement, _ = fixes[i]
                out.append(replacement)
                i = end
            else:
                out.append(words[i])
                i += 1
        return " ".join(out), [fix for _, (_, _, fix) in sorted(fixes.items())]


def _edges_agree(heard: list[str], name: list[str]) -> bool:
    return all(heard[edge] == name[edge] or heard[edge] not in _FILLER for edge in (0, -1))
