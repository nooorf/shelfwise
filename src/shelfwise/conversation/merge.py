"""One turn's parse merged into the conversation state (design doc §17, merge rules).

| The person says                              | State operation                                  |
| -------------------------------------------- | ------------------------------------------------ |
| a constraint on a new field                  | add                                              |
| one on a field already constrained           | replace: later wins (see `_slot`)                |
| "darker", "shorter", "newer"                 | a shift, made absolute from the last results     |
| "forget the page limit"                      | remove that field                                |
| "the second one", "the first two"            | resolved to shown books before anything else     |
| a new topic (new words, a seed, a lookup)    | reset, keeping availability and language; undo   |
| "start over"                                 | full reset                                       |
| "hi", "surprise me"                          | nothing (a surprise may add constraints)         |

"Refine" means the turn only adjusts: the parser said `refine`, or the turn carries constraints
or removals but no topic of its own ("I don't want anything supernatural", "under 300 pages").
Anything with its own topic words, seed or lookup starts a new topic. A similarity test between
old and new topic would catch "and some horror too" as an addition; until set C shows that's
needed, a new topic is a new topic, with undo one tap away.
"""

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from shelfwise.conversation.references import resolve_references
from shelfwise.conversation.state import (
    MAX_RECENT_TURNS,
    ActiveConstraint,
    ConversationState,
    ShownBook,
    Turn,
    new_state,
)
from shelfwise.ingest.normalize import fold_text
from shelfwise.query.constraints import Constraint
from shelfwise.query.request import ParsedRequest

# They describe the person, not the topic, so a new topic keeps them.
USER_FIELDS = frozenset({"available_now", "language"})
SHORTER, LONGER = 0.75, 1.25  # "shorter": under 3/4 of the shown median page count
_PACE = ("slow", "medium", "fast")
_SCALES = ("facet.darkness", "facet.romance", "facet.violence")

_START_OVER = re.compile(
    r"\b(?:start (?:over|again|afresh)|new search|reset|clear (?:everything|all|it)"
    r"|forget (?:everything|all of (?:it|that)))\b"
)
_FORGET = re.compile(
    r"\b(?:forget|drop|remove|ignore|never ?mind|scrap|no need for)"
    r"(?: about)?(?: the| my| that)? (.+)$"
)
# Words that name a constraint field, for "forget the page limit" and chip removal by voice.
# A message that is only a comparison ("something darker", "a bit shorter please"): the shift,
# for when the parse has none (rules-only mode, or the LLM missed it).
_COMPARATIVES = {
    r"darker": ("facet.darkness", 1), r"lighter|less dark": ("facet.darkness", -1),
    r"shorter": ("pages", -1), r"longer": ("pages", 1),
    r"newer|more (?:recent|modern)": ("year", 1), r"older": ("year", -1),
    r"faster(?: paced)?": ("facet.pace", 1), r"slower(?: paced)?": ("facet.pace", -1),
    r"more roman(?:ce|tic)": ("facet.romance", 1), r"less roman(?:ce|tic)": ("facet.romance", -1),
    r"more violen(?:ce|t)": ("facet.violence", 1), r"less violen(?:ce|t)": ("facet.violence", -1),
}  # fmt: skip
_FILLER = re.compile(
    r"\b(?:something|smth|anything|one|ones|a|an|the|bit|little|lot|much|way|even|slightly"
    r"|maybe|please|pls|and|but|make it|can you|could you|i want|i d like|show me|ok|okay"
    r"|let s|lets|now|instead|actually|go|book|books|than that|than those|than these)\b"
)
_LIKE = re.compile(r"\b(?:like|similar to|more of|in the style of)\b")
_FIELD_WORDS = {
    "pages": r"pages?|page (?:limit|count)|length|long|short",
    "year": r"years?|dates?|decade|recent|old|published",
    "available_now": r"availab\w*|in stock|on the shelf|checked out",
    "genre": r"genres?",
    "facet.darkness": r"dark\w*|light\w*|bleak|cozy",
    "facet.romance": r"romance|romantic|love",
    "facet.violence": r"violen\w*|gore|gory",
    "facet.pace": r"pace|paced|speed|fast|slow",
    "facet.supernatural": r"supernatural|magic|paranormal",
    "facet.audience": r"audience|ya|teens?|kids|children|adults?",
}

TurnKind = Literal["new_search", "refine", "new_topic", "start_over", "reference", "chat"]


@dataclass(frozen=True)
class TurnUpdate:
    state: ConversationState
    kind: TurnKind
    targets: list[int] = field(default_factory=list)  # shown books the message pointed at
    kept: list[str] = field(default_factory=list)  # what a topic reset kept ("available now")
    removed: list[str] = field(default_factory=list)  # fields "forget the ..." took away
    unresolved: list[str] = field(default_factory=list)  # shifts with nothing to shift from


_SHIFT_WORDS = {
    ("pages", -1): "shorter", ("pages", 1): "longer", ("year", 1): "newer", ("year", -1): "older",
    ("facet.darkness", 1): "darker", ("facet.darkness", -1): "lighter",
    ("facet.romance", 1): "more romance", ("facet.romance", -1): "less romance",
    ("facet.violence", 1): "more violence", ("facet.violence", -1): "less violence",
    ("facet.pace", 1): "faster", ("facet.pace", -1): "slower",
}  # fmt: skip


_SCALE_WORDS = {
    # field: (lte 0 / eq 0, lte 1, lte 2, gte 2, gte 3)
    "facet.darkness": ("not dark at all", "not too dark", "not bleak", "dark", "very dark"),
    "facet.romance": ("no romance", "little or no romance", "some romance at most", "romantic",
                      "very romantic"),
    "facet.violence": ("no violence", "not too violent", "nothing graphic", "violent",
                       "very violent"),
}  # fmt: skip
_EQ_WORDS = {
    ("facet.pace", "fast"): "fast-paced", ("facet.pace", "slow"): "slow-paced",
    ("facet.pace", "medium"): "steady pace",
    ("facet.supernatural", "yes"): "magic or the supernatural",
    ("facet.audience", "ya"): "for teens", ("facet.audience", "children"): "for kids",
    ("facet.audience", "adult"): "for adults",
    ("facet.fiction", True): "fiction", ("facet.fiction", False): "nonfiction",
    ("facet.historical_setting", "yes"): "set in the past",
    ("facet.reading_level", "intro"): "beginner level",
    ("facet.reading_level", "intermediate"): "intermediate level",
    ("facet.reading_level", "advanced"): "advanced level",
    ("available_now", True): "available now", ("popular", True): "popular",
}  # fmt: skip
_BOUND_WORDS = {
    "pages": {"lt": "under {} pages", "lte": "at most {} pages", "gt": "over {} pages",
              "gte": "at least {} pages", "approx": "about {} pages"},
    "year": {"lt": "before {}", "lte": "{} or earlier", "gt": "after {}", "gte": "{} or later",
             "eq": "from {}"},
}  # fmt: skip


def describe(c: Constraint) -> str | None:
    """Plain words for a constraint the person didn't phrase themselves (LLM, state)."""
    negate = c.polarity == "exclude"
    if c.field in _SCALE_WORDS and isinstance(c.value, int) and not negate:
        words = _SCALE_WORDS[c.field]
        if c.op in ("lte", "lt", "eq") and c.value <= 2:
            limit = c.value - (1 if c.op == "lt" else 0)
            return words[max(0, limit)] if c.op != "eq" or c.value == 0 else None
        if c.op in ("gte", "gt"):
            return words[3] if c.value + (1 if c.op == "gt" else 0) <= 2 else words[4]
    if c.op == "eq" and not isinstance(c.value, list) and (c.field, c.value) in _EQ_WORDS:
        if negate and c.field == "facet.supernatural":
            return "nothing supernatural"
        words = _EQ_WORDS[(c.field, c.value)]
        return f"not {words}" if negate else words
    if c.field == "genre" and c.op == "in":
        names = " or ".join(c.value if isinstance(c.value, list) else [c.value])
        return f"no {names}" if negate else names
    if c.field == "theme":
        return f"no {c.value}" if negate else str(c.value)
    if c.field in _BOUND_WORDS and (pattern := _BOUND_WORDS[c.field].get(c.op)):
        return pattern.format(c.value)
    return None


def label(c: Constraint) -> str:
    """How a constraint reads on a chip and in replies: the person's words when known, else
    plain words, else the raw form."""
    if c.span:
        return c.span
    if c.op == "shift" and (words := _SHIFT_WORDS.get((c.field, c.value))):
        return words
    if words := describe(c):
        return words
    return f"{'not ' if c.polarity == 'exclude' else ''}{c.field} {c.op} {c.value}"


def _slot(c: Constraint) -> tuple[object, ...]:
    """Constraints in the same slot replace each other; later wins.

    Pages and year keep a lower and an upper bound apart, so "after 2010" then "before 2020"
    builds a range while "under 200" replaces "under 300". Exclusions of genres and themes
    pile up ("not horror", then "not romance"). Everything else is one slot per field and
    polarity: a new darkness wish replaces the old one, whatever its direction."""
    if c.field in ("pages", "year"):
        direction = {"lt": "upper", "lte": "upper", "gt": "lower", "gte": "lower"}.get(c.op, c.op)
        return (c.field, c.polarity, direction)
    if c.field in ("genre", "theme") and c.polarity == "exclude":
        return (c.field, c.polarity, repr(c.value))
    return (c.field, c.polarity)


def merge_constraints(
    current: list[ActiveConstraint], new: list[Constraint], turn: int
) -> list[ActiveConstraint]:
    slots = {_slot(c) for c in new}
    kept = [a for a in current if _slot(a.constraint) not in slots]
    return kept + [ActiveConstraint(constraint=c, turn=turn) for c in new]


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def resolve_shift(c: Constraint, shown: list[ShownBook]) -> Constraint | None:
    """A relative change made absolute against what was shown (design doc §12.3): "darker" is
    darkness above the shown median; "shorter" is under 3/4 of the median page count. None
    when there is nothing to compare with."""
    if c.op != "shift":
        return c
    up = isinstance(c.value, int | float) and c.value > 0
    span = c.span or _SHIFT_WORDS.get((c.field, 1 if up else -1), "")

    def made(field_: str, op: str, value: object) -> Constraint:
        # "Shorter" means every book shorter: a hard, visible, removable limit. Moods stay soft.
        strength = "hard" if field_ in ("pages", "year") else c.strength
        update = {"field": field_, "op": op, "value": value, "source": "state", "span": span,
                  "strength": strength}  # fmt: skip
        return c.model_copy(update=update)

    if c.field in _SCALES:
        median = _median([v for b in shown if (v := getattr(b, c.field[6:])) is not None])
        if median is None:
            return None
        if up:
            return made(c.field, "gte", min(3, int(median) + 1))
        # Strictly past the median: "darker" than 2.5 is 3+, "lighter" is 2 or less.
        return made(c.field, "lte", max(0, math.ceil(median) - 1))
    if c.field == "facet.pace":
        paces = [_PACE.index(b.pace) for b in shown if b.pace in _PACE]
        if not paces:
            return None
        step = min(2, max(0, round(statistics.median(paces)) + (1 if up else -1)))
        return made(c.field, "eq", _PACE[step])
    if c.field == "pages":
        median = _median([b.pages for b in shown if b.pages])
        if median is None:
            return None
        if up:
            return made("pages", "gt", round(median * LONGER))
        return made("pages", "lt", round(median * SHORTER))
    if c.field == "year":
        median = _median([b.year for b in shown if b.year])
        if median is None:
            return None
        return made("year", "gt" if up else "lt", int(median))
    return None


def only_content(text: str) -> str:
    """`text` without filler words: "" when nothing of substance is left."""
    return " ".join(_FILLER.sub(" ", text).split())


def comparison_shifts(text: str) -> list[Constraint]:
    """The shifts of a message that is only a comparison; [] if it says anything else."""
    shifts, rest = [], text
    for pattern, (field_, step) in _COMPARATIVES.items():
        if re.search(rf"\b(?:{pattern})\b", rest):
            rest = re.sub(rf"\b(?:{pattern})\b", " ", rest)
            shifts.append(
                Constraint(field=field_, op="shift", value=step, strength="soft", source="rule")
            )
    return shifts if shifts and not only_content(rest) else []


def removed_fields(message: str) -> list[str]:
    """Fields a "forget the page limit" / "never mind the availability" names."""
    match = _FORGET.search(fold_text(message))
    if match is None:
        return []
    words = match.group(1)
    return [f for f, pattern in _FIELD_WORDS.items() if re.search(rf"\b(?:{pattern})\b", words)]


def apply_turn(
    state: ConversationState, message: str, parsed: ParsedRequest, now: datetime
) -> TurnUpdate:
    """The state after one message; `parsed` is that message's own parse."""
    text = fold_text(message)
    state = state.model_copy(deep=True)
    state.turn += 1
    state.last_active = now
    turns = [*state.recent_turns, Turn(text=message, intent=parsed.intent)]
    state.recent_turns = turns[-MAX_RECENT_TURNS:]

    if _START_OVER.search(text):
        fresh = new_state(state.session_id, now).model_copy(
            update={"mode": state.mode, "turn": state.turn, "recent_turns": state.recent_turns}
        )
        # Decided on the message, not the parse: the rules may have taken "over" for a number.
        if not only_content(_START_OVER.sub(" ", text)):
            return TurnUpdate(fresh, "start_over")
        topic = only_content(_START_OVER.sub(" ", fold_text(parsed.semantic_query)))
        state = fresh  # "start over: something funny" is a new search on a clean slate
        parsed = parsed.model_copy(update={"semantic_query": topic})

    if not any(c.op == "shift" for c in parsed.constraints) and (shifts := comparison_shifts(text)):
        parsed = parsed.model_copy(
            update={"intent": "refine", "semantic_query": "",
                    "constraints": [*parsed.constraints, *shifts]}
        )  # fmt: skip

    if parsed.intent in ("other", "surprise"):  # "hi", "surprise me": the topic stays as it is
        if parsed.intent == "surprise":  # "surprise me, something i can borrow today"
            plain = [c for c in parsed.constraints if c.op != "shift"]
            state.constraints = merge_constraints(state.constraints, plain, state.turn)
        return TurnUpdate(state, "chat")

    shown = [b.work_id for b in state.last_results]
    targets = resolve_references(message, shown)
    if parsed.intent in ("explain", "compare") or (targets and not _LIKE.search(text)):
        return TurnUpdate(state, "reference", targets=targets)
    reseed = bool(targets)
    if reseed:  # "more like the second one": a refinement whose seed is that book
        titles = {b.work_id: b.title for b in state.last_results}
        parsed = parsed.model_copy(
            update={"intent": "refine", "seed_work_ids": targets,
                    "seed_titles": [titles[t] for t in targets]}
        )  # fmt: skip

    removed = removed_fields(message)
    if removed:
        state.constraints = [a for a in state.constraints if a.constraint.field not in removed]

    unresolved: list[str] = []
    constraints = []
    for c in parsed.constraints:
        absolute = resolve_shift(c, state.last_results)
        if absolute is None:
            unresolved.append(label(c))
        else:
            constraints.append(absolute)

    own_topic = bool(parsed.semantic_query or parsed.seed_work_ids or parsed.lookup)
    refine = parsed.intent == "refine" or not own_topic
    if not state.has_search and not removed:
        kind: TurnKind = "new_search"
    elif refine:
        kind = "refine"
    else:
        kind = "new_topic"

    kept: list[str] = []
    if kind == "refine":
        if parsed.semantic_query:
            state.semantic_query = f"{state.semantic_query} {parsed.semantic_query}".strip()
        if parsed.lookup:  # "only the stephen king ones"
            state.lookup = parsed.lookup
        if reseed:
            state.seed_titles, state.seed_work_ids = [], []
        for title, work_id in zip(parsed.seed_titles, parsed.seed_work_ids, strict=False):
            if work_id not in state.seed_work_ids:
                state.seed_titles.append(title)
                state.seed_work_ids.append(work_id)
    else:
        if kind == "new_topic":
            state.before_reset = state.snapshot()
            state.constraints = [a for a in state.constraints if a.constraint.field in USER_FIELDS]
            kept = [label(a.constraint) for a in state.constraints]
        state.semantic_query = parsed.semantic_query
        state.lookup = parsed.lookup
        state.seed_titles = list(parsed.seed_titles)
        state.seed_work_ids = list(parsed.seed_work_ids)
    state.constraints = merge_constraints(state.constraints, constraints, state.turn)
    return TurnUpdate(state, kind, kept=kept, removed=removed, unresolved=unresolved)


def undo_reset(state: ConversationState, now: datetime) -> ConversationState | None:
    """The state before the last topic reset, or None if there is nothing to undo."""
    if state.before_reset is None:
        return None
    return state.before_reset.model_copy(
        update={"last_active": now, "turn": state.turn, "recent_turns": state.recent_turns}
    )


def record_results(state: ConversationState, shown: list[ShownBook]) -> ConversationState:
    """What this turn showed: the reference point for the next "shorter" or "the second one"."""
    seen = dict.fromkeys([*state.shown_ids, *(b.work_id for b in shown)])
    return state.model_copy(update={"last_results": shown, "shown_ids": list(seen)})
