"""Conversation memory as a typed state object, updated by deltas (design doc §17).

The retrieval pipeline reads only this state, never a transcript; the LLM will see it plus the
last three turns for tone. Everything here is JSON-serializable, so a session survives a
process restart in Redis (`conversation.store`).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from shelfwise.query.constraints import Constraint
from shelfwise.query.request import Intent, LookupSpec

MAX_RECENT_TURNS = 3


class ShownBook(BaseModel):
    """A book as it was shown: what "the second one" and "something shorter" refer to."""

    work_id: int
    title: str
    pages: int | None = None
    year: int | None = None
    darkness: int | None = None
    romance: int | None = None
    violence: int | None = None
    pace: str | None = None


class ActiveConstraint(BaseModel):
    constraint: Constraint
    turn: int  # the turn that said it, for the chips and for debugging


class Offer(BaseModel):
    """A relaxation put to the reader: drop these constraints, get `count` books."""

    label: str  # "after 2015"
    constraints: list[Constraint]  # what dropping it removes (two for "the 2010s")
    count: int
    earliest_due: date | None = None  # for "available now": the first copy back


class Turn(BaseModel):
    text: str
    intent: Intent


class ConversationState(BaseModel):
    session_id: str
    mode: Literal["text", "voice"] = "text"  # last input modality; display only
    last_active: datetime
    turn: int = 0
    constraints: list[ActiveConstraint] = Field(default_factory=list)
    semantic_query: str = ""  # current mood and topic words
    lookup: LookupSpec | None = None
    seed_titles: list[str] = Field(default_factory=list)
    seed_work_ids: list[int] = Field(default_factory=list)
    last_results: list[ShownBook] = Field(default_factory=list)  # ordered, as shown
    shown_ids: list[int] = Field(default_factory=list)  # everything shown this session
    declined_relaxations: list[str] = Field(default_factory=list)  # labels: never re-offered
    offers: list[Offer] = Field(default_factory=list)  # awaiting an answer, most results first
    recent_turns: list[Turn] = Field(default_factory=list)  # the last MAX_RECENT_TURNS
    # The state just before a topic reset, so "undo" can bring it back (one level).
    before_reset: "ConversationState | None" = None

    @property
    def active(self) -> list[Constraint]:
        return [a.constraint for a in self.constraints]

    @property
    def has_search(self) -> bool:
        """Whether there is anything to refine."""
        return bool(self.semantic_query or self.seed_work_ids or self.lookup or self.constraints)

    def snapshot(self) -> "ConversationState":
        """A copy for `before_reset`, without its own undo history."""
        return self.model_copy(update={"before_reset": None}, deep=True)


def new_state(session_id: str, now: datetime) -> ConversationState:
    return ConversationState(session_id=session_id, last_active=now)
