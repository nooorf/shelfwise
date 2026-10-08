"""One conversation turn, end to end (design doc §8 intent routing, §17 memory).

    load state -> parse the message -> merge (`apply_turn`) -> route -> remember what was shown

| Route      | When                                         | What happens                                   |
| ---------- | -------------------------------------------- | ---------------------------------------------- |
| search     | lookup, discover, similar, refine            | `parsed_hybrid` on the merged state            |
| explain    | "tell me about the second one"               | that book's card and tags; no retrieval        |
| compare    | "which is darker?", "compare the first two"  | the books' cards and tags side by side         |
| clarify    | "tell me about that one" with five shown     | asks which one                                 |
| surprise   | "surprise me"                                | three unseen, available, reasonably popular    |
| chat       | "hi", "what are your hours"                  | a short reply; no books                        |
| start_over | "start over"                                 | empty state                                    |

Replies are fixed templates (`notes`) until narration and its validator land; cards never come
from the LLM. In rules-only mode (no LLM, or it failed) a new topic is retrieved from the raw
message, which finds known items better than a rules-only parse can, and a refinement from the
merged state. "Surprise me" is a placeholder for §15.5's safe / stretch / wildcard picks,
which need the embedding clusters.
"""

import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection

from shelfwise.conversation.merge import (
    TurnUpdate,
    answer_offer,
    answer_turn,
    apply_turn,
    label,
    record_results,
    undo_reset,
)
from shelfwise.conversation.state import ConversationState, Offer, ShownBook, new_state
from shelfwise.conversation.store import SessionStore, new_session_id
from shelfwise.evaluation.systems import SearchContext
from shelfwise.generation.context import Candidate, descriptions, matched_labels
from shelfwise.generation.narrate import Narrator, Reply
from shelfwise.generation.templates import Task
from shelfwise.generation.validate import CatalogNames
from shelfwise.pipeline import BookResult, Relaxation, SearchService
from shelfwise.query.constraints import Constraint, contradictions
from shelfwise.query.request import Intent, LookupSpec, ParsedRequest
from shelfwise.retrieval.filters import allowed_mask, relaxations

Route = Literal["search", "explain", "compare", "clarify", "surprise", "chat", "start_over"]
SURPRISE_PICKS = 3
MAX_OFFERS = 3
SURPRISE_POPULARITY_FLOOR = 0.3  # percentile: a quality floor (design doc §15.5)
_FIELD_WORDS = {
    "pages": "the page limit", "year": "the dates", "available_now": "availability",
    "genre": "the genre", "language": "the language",
}  # fmt: skip
CHAT_REPLY = (
    "I can help you find books in this library: describe what you'd like to read, name a book "
    "or an author, or ask for something like a book you loved."
)


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    narrate: bool = True  # the LLM's notes on the books; off for speed (cards are the same)


class Chip(BaseModel):
    """An active constraint as the UI shows it; removable by naming its field."""

    label: str
    field: str
    op: str
    value: Any
    strength: str
    polarity: str
    turn: int


class TurnResponse(BaseModel):
    session_id: str
    turn: int
    kind: str  # what the turn did to the state: new_search, refine, new_topic, ..., undo
    route: Route
    intent: Intent
    parser: str  # "cascade" or "rules"
    parse_error: str | None
    system: str | None  # the retrieval system, when there was a search
    notes: list[str]  # short template replies: "New search (kept: available now)."
    chips: list[Chip]
    semantic_query: str
    lookup: LookupSpec | None
    seed_titles: list[str]
    results: list[BookResult]
    reply: Reply | None  # intro, one validated note per book, follow-up; None if not asked for
    facets: dict[int, dict[str, Any]]  # explain / compare: the tags of the books discussed
    relaxations: list[Relaxation]
    can_undo: bool
    timings_ms: dict[str, float]


class SessionNotFound(KeyError):
    """No such session, or it expired."""


def state_request(state: ConversationState, intent: Intent) -> ParsedRequest:
    """What to search for: the merged state, not just the last message."""
    if state.seed_work_ids:
        intent = "similar"
    elif intent not in ("lookup",) or not state.lookup:
        intent = "discover"
    return ParsedRequest(
        intent=intent,
        semantic_query=state.semantic_query,
        lookup=state.lookup,
        seed_titles=state.seed_titles,
        seed_work_ids=state.seed_work_ids,
        constraints=state.active,
    )


def shown_books(results: list[BookResult], facets: dict[int, dict[str, Any]]) -> list[ShownBook]:
    """The shown books with what "shorter" and "darker" are measured against."""
    books = []
    for r in results:
        tags = facets.get(r.work_id, {})
        books.append(
            ShownBook(
                work_id=r.work_id,
                title=r.title,
                pages=r.pages,
                year=r.year,
                darkness=tags.get("darkness"),
                romance=tags.get("romance"),
                violence=tags.get("violence"),
                pace=tags.get("pace"),
            )
        )
    return books


def chips(state: ConversationState) -> list[Chip]:
    """One chip per phrase: "between 150 and 200 pages" is two bounds but one thing to remove."""
    fields = {"field", "op", "value", "strength", "polarity"}
    out: dict[tuple[str, str], Chip] = {}
    for a in state.constraints:
        name = label(a.constraint)
        out.setdefault(
            (a.constraint.field, name),
            Chip(label=name, turn=a.turn, **a.constraint.model_dump(include=fields)),
        )
    return list(out.values())


def offer_note(offers: list[Offer]) -> str:
    """'Nothing matches everything. Dropping "after 2015" gives 7; dropping "available now"
    gives 4, the earliest due back Thu 15 Oct. Which should I drop?'"""
    parts = []
    for o in offers:
        part = f'dropping "{o.label}" gives {o.count}'
        if o.earliest_due:
            part += f", the earliest due back {o.earliest_due:%a %d %b}"
        parts.append(part)
    question = "Shall I?" if len(offers) == 1 else "Which should I drop?"
    listed = "; ".join(parts)
    return f"Nothing matches everything. {listed[0].upper()}{listed[1:]}. {question}"


def _humanize_field(field: str) -> str:
    return _FIELD_WORDS.get(field) or field.removeprefix("facet.").replace("_", " ")


def notes_for(update: TurnUpdate) -> list[str]:
    notes = []
    if update.kind == "new_topic":
        notes.append(
            f"New search (kept: {', '.join(update.kept)})." if update.kept else "New search."
        )
    if update.kind == "start_over":
        notes.append("Starting fresh.")
    if update.removed:
        notes.append("Dropped " + ", ".join(_humanize_field(f) for f in update.removed) + ".")
    for words in update.unresolved:
        notes.append(f'I can\'t tell what "{words}" compares to yet: search for something first.')
    return notes


class ConversationService:
    """One per process, over the search service and a session store."""

    def __init__(
        self,
        search: SearchService,
        store: SessionStore,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        narrator: Narrator | None = None,
    ) -> None:
        self.search = search
        self.store = store
        self.now = now
        # Without an LLM the narrator writes templates: correct, plain.
        self.narrator = narrator or Narrator(None)
        self._names: CatalogNames | None = None
        self._names_version: int | None = None

    def _catalog_names(self, conn: Connection) -> CatalogNames:
        version = self.search.catalog_version
        if self._names is None or version != self._names_version:
            self._names, self._names_version = CatalogNames.load(conn), version
        return self._names

    def _narrate(
        self, conn: Connection, ctx: SearchContext, state: ConversationState, route: Route,
        message: str, results: list[BookResult],
    ) -> Reply | None:  # fmt: skip
        task: Task | None = {"search": "recommend", "surprise": "recommend", "explain": "explain",
                             "compare": "compare"}.get(route)  # type: ignore[assignment]  # fmt: skip
        if task is None or not results:
            return None
        facets = ctx.signals().facets
        texts = descriptions(conn, [r.work_id for r in results])
        wishes = [(label(a.constraint), a.constraint) for a in state.constraints]
        books = [
            Candidate(
                work_id=r.work_id,
                title=r.title,
                authors=r.authors,
                pages=r.pages,
                year=r.year,
                genres=r.genres,
                facets=facets.get(r.work_id, {}),
                matched=matched_labels(wishes, facets.get(r.work_id, {}), r.genres),
                description=texts.get(r.work_id, ""),
            )
            for r in results
        ]
        said = [state.semantic_query] if state.semantic_query else []
        return self.narrator.narrate(
            task, message, books, self._catalog_names(conn), [*said, *(w for w, _ in wishes)],
            state.seed_titles, state.seed_work_ids,
        )  # fmt: skip

    def start(self) -> str:
        session_id = new_session_id()
        self.store.put(new_state(session_id, self.now()))
        return session_id

    def end(self, session_id: str) -> None:
        """ "New visitor": the state is gone immediately, not at expiry."""
        self.store.delete(session_id)

    def _load(self, session_id: str) -> ConversationState:
        state = self.store.get(session_id)
        if state is None:
            raise SessionNotFound(session_id)
        return state

    def turn(self, conn: Connection, session_id: str, request: TurnRequest) -> TurnResponse:
        start = time.perf_counter()
        state = self._load(session_id)
        ctx = self.search.context(conn)
        if (answer := answer_offer(request.message, state.offers)) is not None:
            return self._answer_offer(conn, ctx, state, request, answer, start)
        state.offers = []  # not an answer: the offers lapse
        parsed, parse_error = self.search.parse(conn, request.message, ctx)
        parse_ms = (time.perf_counter() - start) * 1000
        update = apply_turn(state, request.message, parsed, self.now())
        state = update.state
        notes = notes_for(update)
        facets: dict[int, dict[str, Any]] = {}
        system = None
        ids: list[int] = []

        route: Route
        if update.kind == "start_over":
            route = "start_over"
        elif parsed.intent == "surprise":
            route, ids = "surprise", self._surprise(ctx, state)
        elif update.kind == "chat":
            route = "chat"
            notes.append(CHAT_REPLY)
        elif update.kind == "reference":
            route, ids = self._reference(state, parsed.intent, update.targets)
            if route == "clarify":
                notes.append('Which one? You can say "the second one" or tap a book.')
            facets = {w: ctx.signals().facets.get(w, {}) for w in ids}
        else:
            route = "search"
            # Rules-only, a new topic is better found from the raw words (known items);
            # a refinement only makes sense against the state.
            use_parse = (parse_error is None and self.search.llm is not None) or (
                update.kind == "refine"
            )
            query = state.semantic_query or request.message
            system, ids = self.search.retrieve(
                ctx, query, state_request(state, parsed.intent), use_parse, request.limit
            )
        return self._respond(
            conn, ctx, state, update.kind, route, parsed.intent, parse_error, system, ids,
            notes, facets, start, parse_ms, request.message if request.narrate else None,
        )  # fmt: skip

    def _answer_offer(
        self, conn: Connection, ctx: SearchContext, state: ConversationState,
        request: TurnRequest, answer: int | Literal["decline"], start: float,
    ) -> TurnResponse:  # fmt: skip
        """ "Yes" / "drop the year" / "no, keep them": no parsing, no LLM call."""
        update = answer_turn(state, request.message, answer, self.now())
        state = update.state
        message = request.message if request.narrate else None
        if update.declined:
            note = "OK, keeping all of them. You could change what you asked for instead."
            return self._respond(
                conn, ctx, state, "relax", "chat", "refine", None, None, [], [note], {},
                start, 0.0, None,
            )  # fmt: skip
        system, ids = self.search.retrieve(
            ctx, state.semantic_query or request.message, state_request(state, "refine"), True,
            request.limit,
        )  # fmt: skip
        return self._respond(
            conn, ctx, state, "relax", "search", "refine", None, system, ids,
            [f'Dropped "{update.dropped[0]}".'], {}, start, 0.0, message,
        )  # fmt: skip

    def _offers(self, conn: Connection, state: ConversationState) -> list[Offer]:
        """What dropping each hard constraint would give, best first, minus refused ones."""
        if contradictions(state.active):
            return []
        offers = []
        for r in relaxations(conn, state.active):
            name = label(r.dropped[0])
            if r.count and name not in state.declined_relaxations:
                offers.append(Offer(label=name, constraints=list(r.dropped), count=r.count,
                                    earliest_due=r.earliest_due))  # fmt: skip
        return offers[:MAX_OFFERS]

    def undo(
        self, conn: Connection, session_id: str, limit: int = 5, narrate: bool = True
    ) -> TurnResponse:
        """Back to the state before the last topic reset, searched again."""
        start = time.perf_counter()
        state = self._load(session_id)
        ctx = self.search.context(conn)
        restored = undo_reset(state, self.now())
        if restored is None:
            return self._respond(
                conn, ctx, state, "undo", "chat", "other", None, None, [],
                ["Nothing to undo."], {}, start, 0.0, None,
            )  # fmt: skip
        query = restored.semantic_query or "books"
        system, ids = self.search.retrieve(
            ctx, query, state_request(restored, "discover"), True, limit
        )
        said = restored.recent_turns[-1].text if restored.recent_turns else query
        return self._respond(
            conn, ctx, restored, "undo", "search", "refine", None, system, ids,
            ["Back to your previous search."], {}, start, 0.0, said if narrate else None,
        )  # fmt: skip

    def _reference(
        self, state: ConversationState, intent: Intent, targets: list[int]
    ) -> tuple[Route, list[int]]:
        shown = [b.work_id for b in state.last_results]
        if not targets:
            if intent == "compare" and len(shown) > 1:
                targets = shown  # "which of these is darkest?"
            elif len(shown) == 1:
                targets = shown
        if not targets:
            return "clarify", []
        if intent == "compare" or (intent != "explain" and len(targets) > 1):
            return "compare", targets
        return "explain", targets

    def _surprise(self, ctx: SearchContext, state: ConversationState) -> list[int]:
        available = Constraint(field="available_now", op="eq", value=True, strength="hard",
                               source="state")  # fmt: skip
        hard = [c for c in state.active if c.strength == "hard" and c.field != "available_now"]
        mask = allowed_mask(ctx.conn, [*hard, available], ctx.index.work_ids)
        ranks = ctx.signals().popularity_rank
        seen = set(state.shown_ids)
        pool = [
            int(w)
            for w, ok in zip(ctx.index.work_ids.tolist(), mask, strict=True)
            if ok and ranks.get(int(w), 0.0) >= SURPRISE_POPULARITY_FLOOR and int(w) not in seen
        ]
        rng = random.Random(f"{state.session_id}:{state.turn}")  # a new draw on every press
        return rng.sample(pool, min(SURPRISE_PICKS, len(pool)))

    def _respond(
        self, conn: Connection, ctx: SearchContext, state: ConversationState, kind: str,
        route: Route, intent: Intent, parse_error: str | None, system: str | None,
        ids: list[int], notes: list[str], facets: dict[int, dict[str, Any]], start: float,
        parse_ms: float, message: str | None,
    ) -> TurnResponse:  # fmt: skip
        """`message`: what to narrate for (None: no narration)."""
        results = self.search.details(conn, ids, ctx.today)
        relaxations_out: list[Relaxation] = []
        if route == "search" and not results:
            if conflicts := contradictions(state.active):
                notes.append("These can't all hold: " + "; ".join(x.message() for x in conflicts))
            elif offers := self._offers(conn, state):
                state = state.model_copy(update={"offers": offers})
                notes.append(offer_note(offers))
                relaxations_out = [
                    Relaxation(drop=o.label, count=o.count, earliest_due=o.earliest_due)
                    for o in offers
                ]
            else:
                notes.append("Nothing in the catalog matches that.")
        if route in ("search", "surprise"):
            state = record_results(state, shown_books(results, ctx.signals().facets))
        retrieved_ms = (time.perf_counter() - start) * 1000
        reply = None
        if message is not None:
            reply = self._narrate(conn, ctx, state, route, message, results)
        self.store.put(state)
        return TurnResponse(
            session_id=state.session_id,
            turn=state.turn,
            kind=kind,
            route=route,
            intent=intent,
            parser="rules" if parse_error is not None or self.search.llm is None else "cascade",
            parse_error=parse_error,
            system=system,
            notes=notes,
            chips=chips(state),
            semantic_query=state.semantic_query,
            lookup=state.lookup,
            seed_titles=state.seed_titles,
            results=results,
            reply=reply,
            facets=facets,
            relaxations=relaxations_out,
            can_undo=state.before_reset is not None,
            timings_ms={
                "parse": round(parse_ms, 1),
                "retrieve": round(retrieved_ms - parse_ms, 1),
                "narrate": reply.ms if reply else 0.0,
                "total": round((time.perf_counter() - start) * 1000, 1),
            },
        )
