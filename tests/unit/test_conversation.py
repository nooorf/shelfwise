from datetime import UTC, datetime

import pytest

from shelfwise.conversation.merge import (
    apply_turn,
    book_feedback,
    record_results,
    remove_chip,
    removed_fields,
    resolve_shift,
    undo_reset,
)
from shelfwise.conversation.references import resolve_references
from shelfwise.conversation.state import ConversationState, ShownBook, new_state
from shelfwise.conversation.store import MemorySessionStore
from shelfwise.query.constraints import Constraint
from shelfwise.query.request import LookupSpec, ParsedRequest

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def c(field: str, op: str, value: object, strength: str = "soft", exclude: bool = False,
      span: str | None = None) -> Constraint:  # fmt: skip
    return Constraint(
        field=field, op=op, value=value, strength=strength, source="llm",
        polarity="exclude" if exclude else "include", span=span,
    )  # fmt: skip


def parsed(intent: str = "discover", semantic: str = "", *constraints: Constraint,
           **extra: object) -> ParsedRequest:  # fmt: skip
    return ParsedRequest(
        intent=intent, semantic_query=semantic, constraints=list(constraints), **extra
    )


def active(state: ConversationState) -> set[str]:
    return {
        f"{'not ' if x.polarity == 'exclude' else ''}{x.field} {x.op} {x.value} {x.strength}"
        for x in state.active
    }


def shown(*books: dict) -> list[ShownBook]:
    return [ShownBook(work_id=i + 1, title=f"Book {i + 1}", **b) for i, b in enumerate(books)]


def turn(state: ConversationState, message: str, parse: ParsedRequest):  # type: ignore[no-untyped-def]
    return apply_turn(state, message, parse, NOW)


def test_the_design_docs_worked_example() -> None:
    """§17: thrillers -> darker -> nothing supernatural -> under 300 pages -> the second one."""
    state = new_state("s1", NOW)
    one = turn(
        state,
        "give me psychological thrillers",
        parsed("discover", "psychological thrillers", c("genre", "in", ["thriller"])),
    )
    state = record_results(one.state, shown(*({"darkness": d, "pages": 350} for d in (1, 2, 2, 3))))

    two = turn(state, "something darker", parsed("refine", "", c("facet.darkness", "shift", 1)))
    three = turn(
        two.state,
        "i dont want anything supernatural",
        parsed("discover", "", c("facet.supernatural", "eq", "yes", "hard", exclude=True)),
    )
    four = turn(
        three.state,
        "under three hundred pages",
        parsed("discover", "", c("pages", "lt", 300, "hard")),
    )
    five = turn(four.state, "tell me more about the second one", parsed("explain"))

    assert (one.kind, two.kind, three.kind, four.kind, five.kind) == (
        "new_search", "refine", "refine", "refine", "reference"
    )  # fmt: skip
    assert active(four.state) == {
        "genre in ['thriller'] soft",
        "facet.darkness gte 3 soft",  # the median shown was 2
        "not facet.supernatural eq yes hard",
        "pages lt 300 hard",
    }
    assert four.state.semantic_query == "psychological thrillers"
    assert five.targets == [2]
    assert active(five.state) == active(four.state)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (c("pages", "lt", 300, "hard"), c("pages", "lt", 200, "hard"), {"pages lt 200 hard"}),
        (c("year", "gt", 2010, "hard"), c("year", "lt", 2020, "hard"),
         {"year gt 2010 hard", "year lt 2020 hard"}),  # a range, built over two turns
        (c("genre", "in", ["horror"], "hard", exclude=True),
         c("genre", "in", ["romance"], "hard", exclude=True),
         {"not genre in ['horror'] hard", "not genre in ['romance'] hard"}),  # exclusions pile up
        (c("facet.darkness", "gte", 2), c("facet.darkness", "lte", 1, "hard"),
         {"facet.darkness lte 1 hard"}),  # a new wish for the same thing replaces the old one
        (c("genre", "in", ["mystery"]), c("genre", "in", ["horror"]), {"genre in ['horror'] soft"}),
    ],
)  # fmt: skip
def test_later_wins_within_a_slot(first: Constraint, second: Constraint, expected: set) -> None:
    state = turn(new_state("s", NOW), "x", parsed("discover", "books", first)).state

    state = turn(state, "y", parsed("refine", "", second)).state

    assert active(state) == expected


@pytest.mark.parametrize(
    ("shift", "books", "expected"),
    [
        (c("facet.darkness", "shift", 1), [{"darkness": 1}, {"darkness": 2}, {"darkness": 2}],
         "facet.darkness gte 3"),
        (c("facet.darkness", "shift", -1), [{"darkness": 2}, {"darkness": 3}], "facet.darkness lte 2"),
        (c("facet.romance", "shift", -1), [{"romance": 0}], "facet.romance lte 0"),
        (c("pages", "shift", -1), [{"pages": 300}, {"pages": 400}, {"pages": 500}], "pages lt 300"),
        (c("pages", "shift", 1), [{"pages": 200}], "pages gt 250"),
        (c("year", "shift", 1), [{"year": 1990}, {"year": 2000}, {"year": 2010}], "year gt 2000"),
        (c("facet.pace", "shift", 1), [{"pace": "medium"}, {"pace": "slow"}, {"pace": "medium"}],
         "facet.pace eq fast"),
        (c("facet.pace", "shift", -1), [{"pace": "slow"}], "facet.pace eq slow"),
    ],
)  # fmt: skip
def test_shifts_are_made_absolute_from_what_was_shown(
    shift: Constraint, books: list[dict], expected: str
) -> None:
    result = resolve_shift(shift, shown(*books))

    assert result is not None
    assert f"{result.field} {result.op} {result.value}" == expected
    hard = shift.field in ("pages", "year")  # "shorter" limits every book; moods only nudge
    assert (result.source, result.strength) == ("state", "hard" if hard else "soft")


def test_a_shift_with_nothing_to_compare_is_reported_not_guessed() -> None:
    state = turn(new_state("s", NOW), "fantasy", parsed("discover", "fantasy")).state
    state = record_results(state, shown({"pages": None}))

    update = turn(state, "shorter please", parsed("refine", "", c("pages", "shift", -1)))

    assert update.unresolved == ["shorter"]
    assert active(update.state) == set()


@pytest.mark.parametrize(
    ("message", "fields"),
    [
        ("forget the page limit", ["pages"]),
        ("never mind the availability", ["available_now"]),
        ("drop the romance thing", ["facet.romance"]),
        ("something to get lost in", []),
    ],
)
def test_forget_names_the_fields_to_remove(message: str, fields: list[str]) -> None:
    assert removed_fields(message) == fields


def test_forget_removes_the_field() -> None:
    state = turn(new_state("s", NOW), "x",
                 parsed("discover", "thrillers", c("pages", "lt", 300, "hard"),
                        c("available_now", "eq", True, "hard"))).state  # fmt: skip

    update = turn(state, "forget the page limit", parsed("refine"))

    assert update.kind == "refine" and update.removed == ["pages"]
    assert active(update.state) == {"available_now eq True hard"}


def test_a_new_topic_keeps_only_who_the_person_is_and_can_be_undone() -> None:
    state = turn(
        new_state("s", NOW),
        "dark thrillers i can borrow today",
        parsed(
            "discover",
            "dark thrillers",
            c("facet.darkness", "gte", 2),
            c("available_now", "eq", True, "hard", span="borrow today"),
        ),
    ).state
    update = turn(state, "actually, a funny fantasy", parsed("discover", "funny fantasy"))

    assert update.kind == "new_topic"
    assert update.kept == ["borrow today"]
    assert active(update.state) == {"available_now eq True hard"}
    assert update.state.semantic_query == "funny fantasy"
    undone = undo_reset(update.state, NOW)
    assert undone is not None and undone.semantic_query == "dark thrillers"
    assert active(undone) == active(state)
    assert undo_reset(undone, NOW) is None  # one level


def test_start_over_clears_everything_but_can_start_a_new_search() -> None:
    state = turn(
        new_state("s", NOW),
        "x",
        parsed("discover", "thrillers", c("available_now", "eq", True, "hard")),
    ).state

    cleared = turn(state, "start over", parsed("other"))
    fresh = turn(state, "start over, something funny", parsed("discover", "something funny"))

    assert cleared.kind == "start_over" and not cleared.state.has_search
    assert fresh.kind == "new_search" and active(fresh.state) == set()
    assert fresh.state.semantic_query == "funny"  # the start-over words and filler are gone


def test_more_like_a_shown_book_reseeds_and_keeps_the_rest() -> None:
    state = turn(
        new_state("s", NOW),
        "short thrillers",
        parsed("discover", "thrillers", c("pages", "lt", 300, "hard")),
    ).state
    state = record_results(state, shown({}, {}, {}))  # fmt: skip

    update = turn(state, "more like the second one", parsed("similar"))

    assert update.kind == "refine"
    assert (update.state.seed_work_ids, update.state.seed_titles) == ([2], ["Book 2"])
    assert active(update.state) == {"pages lt 300 hard"}


def test_a_refinement_can_narrow_to_an_author() -> None:
    state = turn(new_state("s", NOW), "x", parsed("discover", "horror")).state

    update = turn(state, "only the stephen king ones",
                  parsed("refine", "", lookup=LookupSpec(author="Stephen King")))  # fmt: skip

    assert update.kind == "refine"
    assert update.state.lookup == LookupSpec(author="Stephen King")
    assert update.state.semantic_query == "horror"


def test_recent_turns_and_shown_books_are_remembered() -> None:
    state = new_state("s", NOW)
    for i in range(5):
        state = turn(state, f"message {i}", parsed("discover", f"topic {i}")).state
        state = record_results(state, shown({}, {}))

    assert [t.text for t in state.recent_turns] == ["message 2", "message 3", "message 4"]
    assert state.shown_ids == [1, 2]
    assert state.turn == 5


@pytest.mark.parametrize(
    ("message", "shown_ids", "expected"),
    [
        ("tell me about the second one", [10, 20, 30], [20]),
        ("is number 3 available", [10, 20, 30], [30]),
        ("the last one sounds good", [10, 20, 30], [30]),
        ("compare the first and the last", [10, 20, 30], [10, 30]),
        ("compare the third one and the first", [10, 20, 30], [30, 10]),
        ("the first two", [10, 20, 30], [10, 20]),
        ("what about the 2nd book?", [10, 20], [20]),
        ("the fifth one", [10, 20], []),  # only two shown
        ("the first book in a series", [10, 20], []),  # not a reference
        ("is that one available", [10, 20, 30], []),  # ambiguous with three on screen
        ("is it available", [10], [10]),  # unambiguous with one
        ("tell me about the second one", [], []),
    ],
)
def test_references_resolve_to_shown_books(
    message: str, shown_ids: list[int], expected: list[int]
) -> None:
    assert resolve_references(message, shown_ids) == expected


def test_state_round_trips_through_json_with_its_undo() -> None:
    state = turn(
        new_state("s", NOW), "x", parsed("discover", "dark", c("facet.darkness", "gte", 2))
    ).state
    state = turn(state, "y", parsed("discover", "funny")).state  # fmt: skip

    again = ConversationState.model_validate_json(state.model_dump_json())

    assert again == state
    assert again.before_reset is not None and again.before_reset.semantic_query == "dark"


def test_memory_store_expires_idle_sessions() -> None:
    now = [0.0]
    store = MemorySessionStore(ttl_s=120, clock=lambda: now[0])
    store.put(new_state("kiosk", NOW))

    now[0] = 119.0
    assert store.get("kiosk") is not None
    now[0] = 121.0
    assert store.get("kiosk") is None


def test_routing_helpers() -> None:
    from shelfwise.conversation.merge import TurnUpdate
    from shelfwise.conversation.service import ConversationService, notes_for, state_request

    state = turn(new_state("s", NOW), "x", parsed("discover", "horror")).state
    state = record_results(state, shown({}, {}, {}))
    route = ConversationService._reference

    assert route(None, state, "explain", [2]) == ("explain", [2])  # type: ignore[arg-type]
    assert route(None, state, "compare", []) == ("compare", [1, 2, 3])  # type: ignore[arg-type]
    assert route(None, state, "explain", []) == ("clarify", [])  # type: ignore[arg-type]
    assert route(None, state, "discover", [1, 3]) == ("compare", [1, 3])  # type: ignore[arg-type]

    seeded = state.model_copy(update={"seed_work_ids": [7], "seed_titles": ["Dune"]})
    assert state_request(seeded, "refine").intent == "similar"
    assert state_request(state, "refine").intent == "discover"
    authored = state.model_copy(update={"lookup": LookupSpec(author="Stephen King")})
    assert state_request(authored, "lookup").intent == "lookup"

    notes = notes_for(TurnUpdate(state, "new_topic", kept=["borrow today"], removed=["pages"],
                                 unresolved=["shorter"]))  # fmt: skip
    assert notes == [
        "New search (kept: borrow today).",
        "Dropped the page limit.",
        'I can\'t tell what "shorter" compares to yet: search for something first.',
    ]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("something darker", ["facet.darkness shift 1"]),
        ("a bit shorter please", ["pages shift -1"]),
        ("shorter and less romantic", ["pages shift -1", "facet.romance shift -1"]),
        ("darker fantasy with dragons", []),  # a topic of its own
        ("dragons", []),
    ],
)
def test_comparison_only_messages(message: str, expected: list[str]) -> None:
    from shelfwise.conversation.merge import comparison_shifts

    assert [f"{x.field} {x.op} {x.value}" for x in comparison_shifts(message)] == expected


def test_rules_only_refinements_and_start_over() -> None:
    """Without the LLM the parse of "something darker" is just its words (the rules' residual);
    the merge still sees a refinement. "start over" alone is not a search for "start over"."""
    state = turn(new_state("s", NOW), "x", parsed("discover", "dark fantasy")).state
    state = record_results(state, shown({"darkness": 1}, {"darkness": 2}, {"darkness": 2}))

    darker = turn(state, "something darker", parsed("discover", "something darker"))
    over = turn(darker.state, "start over", parsed("discover", "start"))  # rules took "over"

    assert darker.kind == "refine"
    assert darker.state.semantic_query == "dark fantasy"
    assert active(darker.state) == {"facet.darkness gte 3 soft"}
    assert over.kind == "start_over" and not over.state.has_search


@pytest.mark.parametrize(
    ("constraint", "words"),
    [
        (c("facet.darkness", "lte", 1, "hard"), "not too dark"),
        (c("facet.darkness", "gte", 3), "very dark"),
        (c("facet.romance", "eq", 0, "hard"), "no romance"),
        (c("facet.violence", "lte", 2, "hard"), "nothing graphic"),
        (c("facet.supernatural", "eq", "yes", "hard", exclude=True), "nothing supernatural"),
        (c("facet.audience", "eq", "adult"), "for adults"),
        (c("genre", "in", ["fantasy"]), "fantasy"),
        (c("genre", "in", ["horror"], "hard", exclude=True), "no horror"),
        (c("theme", "eq", "space", exclude=True), "no space"),
        (c("pages", "lt", 240, "hard"), "under 240 pages"),
        (c("year", "gt", 2015, "hard"), "after 2015"),
        (c("facet.darkness", "shift", 1), "darker"),
        (c("pages", "lt", 300, "hard", span="short ones"), "short ones"),  # their words win
    ],
)
def test_chips_read_as_plain_words(constraint: Constraint, words: str) -> None:
    from shelfwise.conversation.merge import label

    assert label(constraint) == words


def offers_for_test():  # type: ignore[no-untyped-def]
    from datetime import date

    from shelfwise.conversation.state import Offer

    return [
        Offer(label="after 2015", constraints=[c("year", "gt", 2015, "hard")], count=7),
        Offer(label="available now", constraints=[c("available_now", "eq", True, "hard")],
              count=4, earliest_due=date(2026, 10, 15)),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("message", "answer"),
    [
        ("yes", 0),  # the one with the most books
        ("ok then", 0),
        ("sure, drop it", 0),
        ("drop the year", 0),
        ("after 2015 can go", 0),
        ("the second one", 1),
        ("forget the availability", 1),
        ("no", "decline"),
        ("no thanks, keep them", "decline"),
        ("no romance please", None),  # a new request, not a refusal
        ("something funny instead", None),
    ],
)
def test_answers_to_relaxation_offers(message: str, answer: object) -> None:
    from shelfwise.conversation.merge import answer_offer

    assert answer_offer(message, offers_for_test()) == answer


def test_accepting_drops_the_constraint_and_declining_is_remembered() -> None:
    from shelfwise.conversation.merge import answer_turn
    from shelfwise.conversation.service import offer_note

    state = turn(
        new_state("s", NOW),
        "x",
        parsed(
            "discover",
            "mystery",
            c("year", "gt", 2015, "hard"),
            c("available_now", "eq", True, "hard"),
        ),
    ).state
    state = state.model_copy(update={"offers": offers_for_test()})  # fmt: skip

    accepted = answer_turn(state, "the second one", 1, NOW)
    declined = answer_turn(state, "no", "decline", NOW)

    assert accepted.dropped == ["available now"] and accepted.state.offers == []
    assert active(accepted.state) == {"year gt 2015 hard"}
    assert declined.state.declined_relaxations == ["after 2015", "available now"]
    assert active(declined.state) == active(state)
    assert offer_note(offers_for_test()) == (
        'Nothing matches everything. Dropping "after 2015" gives 7; dropping "available now" '
        "gives 4, the earliest due back Thu 15 Oct. Which should I drop?"
    )


def test_a_removal_is_never_small_talk() -> None:
    state = turn(
        new_state("s", NOW), "x", parsed("discover", "cyberpunk", c("year", "eq", 2025, "hard"))
    ).state

    update = turn(state, "drop the year", parsed("other"))
    worded = turn(state, "drop the year", parsed("discover", "drop the year"))  # fmt: skip

    assert (update.kind, update.removed) == ("refine", ["year"])
    assert active(update.state) == set()
    assert (worded.kind, worded.state.semantic_query) == ("refine", "cyberpunk")


def test_a_bare_ordinal_is_a_reference_even_if_the_parser_says_small_talk() -> None:
    state = turn(new_state("s", NOW), "x", parsed("discover", "horror")).state
    state = record_results(state, shown({}, {}, {}))

    update = turn(state, "the second one", parsed("other"))

    assert (update.kind, update.targets) == ("reference", [2])


def test_removing_a_chip_drops_everything_behind_it() -> None:
    state = turn(new_state("s", NOW), "x",
                 parsed("discover", "thrillers",
                        c("pages", "gte", 150, "hard", span="between 150 and 200 pages"),
                        c("pages", "lte", 200, "hard", span="between 150 and 200 pages"),
                        c("available_now", "eq", True, "hard"))).state  # fmt: skip

    update = remove_chip(state, "pages", "between 150 and 200 pages", NOW)

    assert update is not None and update.kind == "remove"
    assert update.dropped == ["between 150 and 200 pages"]
    assert active(update.state) == {"available_now eq True hard"}
    assert update.state.semantic_query == "thrillers" and update.state.turn == state.turn + 1
    assert remove_chip(update.state, "pages", "between 150 and 200 pages", NOW) is None


def test_more_like_this_reseeds_and_less_like_this_hides() -> None:
    state = turn(
        new_state("s", NOW),
        "x",
        parsed("discover", "thrillers", c("available_now", "eq", True, "hard")),
    ).state

    more = book_feedback(state, 7, "Gone Girl", True, NOW)
    assert (more.kind, more.state.seed_work_ids, more.state.seed_titles) == (
        "more_like",
        [7],
        ["Gone Girl"],
    )
    assert active(more.state) == active(state) and more.state.semantic_query == "thrillers"

    less = book_feedback(more.state, 7, "Gone Girl", False, NOW)
    assert less.kind == "less_like"
    assert (less.state.seed_work_ids, less.state.avoid_work_ids) == ([], [7])
    again = book_feedback(less.state, 7, "Gone Girl", True, NOW)
    assert again.state.avoid_work_ids == []  # changed their mind
