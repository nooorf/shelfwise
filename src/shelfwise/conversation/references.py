"""Which shown books a message points at: "the second one", "number 3", "the first two".

Resolved before anything else is parsed (design doc §17), against the last results in the order
they were shown. Only unambiguous forms resolve: "that one" with five books on screen could be
any of them, so it resolves to nothing and the caller asks (a tap on a card carries its own id).
"""

import re

from shelfwise.ingest.normalize import fold_text

_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4, "sixth": 5, "6th": 5, "seventh": 6, "7th": 6, "eighth": 7, "8th": 7,
    "ninth": 8, "9th": 8, "tenth": 9, "10th": 9, "last": -1,
}  # fmt: skip
_COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5, "2": 2, "3": 3, "4": 4, "5": 5}
_ORDINAL = "|".join(_ORDINALS)
# "the second one", "the last book", "the 3rd result"; not "the first book in a series".
_SINGLE = re.compile(rf"\b(?:the )?({_ORDINAL}) (?:one|book|result|option|title)\b(?! (?:in|of)\b)")
# "the second", "the first and the last": a bare ordinal, at the end or before a joining word.
_BARE = re.compile(rf"\bthe ({_ORDINAL})(?= (?:and|or|vs|versus|with|please)\b|$)")
_NUMBER = re.compile(r"\b(?:number|no|book|result|option) (\d{1,2})\b")
_FIRST_N = re.compile(rf"\bthe (?:first|top) ({'|'.join(_COUNTS)})\b")
_DEICTIC = re.compile(r"\b(?:that|this|the) (?:one|book)\b|\bit\b")


def resolve_references(message: str, shown: list[int]) -> list[int]:
    """Work ids from `shown` the message refers to, in the order mentioned; [] when none or
    ambiguous. "it" / "that one" resolve only when exactly one book was shown."""
    if not shown:
        return []
    text = fold_text(message)
    if match := _FIRST_N.search(text):
        return shown[: _COUNTS[match.group(1)]]
    mentions = [(m.start(), _ORDINALS[m.group(1)]) for m in _SINGLE.finditer(text)]
    mentions += [(m.start(), _ORDINALS[m.group(1)]) for m in _BARE.finditer(text)]
    mentions += [(m.start(), int(m.group(1)) - 1) for m in _NUMBER.finditer(text)]
    picked: list[int] = []
    for _, index in sorted(mentions):
        if -len(shown) <= index < len(shown) and shown[index] not in picked:
            picked.append(shown[index])
    if not picked and len(shown) == 1 and _DEICTIC.search(text):
        picked.append(shown[0])
    return picked
