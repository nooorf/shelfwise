"""Spelled-out numbers, as voice transcripts produce them: "three hundred and fifty" -> 350."""

import re

_UNIT_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
)
_TEN_WORDS = "twenty thirty forty fifty sixty seventy eighty ninety"
_UNITS = {w: i for i, w in enumerate(_UNIT_WORDS.split())}
_TENS = {w: 10 * i for i, w in enumerate(_TEN_WORDS.split(), start=2)}
NUMBER_WORDS = (*_UNITS, *_TENS, "hundred", "thousand", "a")
_NUMBER_PHRASE = (
    r"(?:(?:" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")(?:[\s-]+and)?[\s-]+)*"
    r"(?:" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
)
NUMBER_PHRASE = re.compile(rf"\b{_NUMBER_PHRASE}\b")


def words_to_number(phrase: str) -> int | None:
    """Parse "three hundred and fifty" or "a hundred"; None if the phrase isn't a number."""
    total = current = 0
    seen_number = False
    for word in re.split(r"[\s-]+", phrase.lower().strip()):
        if word in ("and", ""):
            continue
        if word == "a":
            current = max(current, 1)
            continue
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            return None
        seen_number = True
    return total + current if seen_number else None
