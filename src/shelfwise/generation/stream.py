"""Pieces of the narration JSON as soon as each is complete.

The model streams `{"intro": "...", "items": [{"work_id": 3, "why": "..."}, ...],
"follow_up": "..."}` token by token. `PieceParser` takes the text as it arrives and hands out
each string once its closing quote is in: the intro, every item, the follow-up. It's a
scanner for this one shape, not a general JSON parser; the finished text is still validated
as a whole by the schema afterwards.
"""

import json
import re
from dataclasses import dataclass
from typing import Literal

_STRING = r'"((?:[^"\\]|\\.)*)"'
_INTRO = re.compile(r'"intro"\s*:\s*' + _STRING)
_ITEM = re.compile(r'\{\s*"work_id"\s*:\s*(\d+)\s*,\s*"why"\s*:\s*' + _STRING + r"\s*\}")
_FOLLOW_UP = re.compile(r'"follow_up"\s*:\s*' + _STRING)


@dataclass(frozen=True)
class Piece:
    kind: Literal["intro", "item", "follow_up"]
    text: str
    work_id: int | None = None


def _unescape(raw: str) -> str:
    try:
        return str(json.loads(f'"{raw}"'))
    except json.JSONDecodeError:
        return raw


class PieceParser:
    def __init__(self) -> None:
        self.text = ""
        self._intro = False
        self._items = 0
        self._follow_up = False

    def feed(self, delta: str) -> list[Piece]:
        """The pieces this delta completed, in the order the model wrote them."""
        self.text += delta
        found: list[Piece] = []
        if not self._intro and (m := _INTRO.search(self.text)):
            self._intro = True
            found.append(Piece("intro", _unescape(m.group(1))))
        items = _ITEM.findall(self.text)
        for work_id, why in items[self._items :]:
            found.append(Piece("item", _unescape(why), int(work_id)))
        self._items = len(items)
        if not self._follow_up and (m := _FOLLOW_UP.search(self.text)):
            self._follow_up = True
            found.append(Piece("follow_up", _unescape(m.group(1))))
        return found
