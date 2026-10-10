import pytest
from pydantic import ValidationError

from shelfwise.generation import templates
from shelfwise.generation.context import Candidate, matched_labels
from shelfwise.generation.narrate import Narrator, reply_schema
from shelfwise.generation.validate import CatalogNames, check, missing_key
from shelfwise.llm.client import LLMUnavailable
from shelfwise.query.constraints import Constraint
from tests.fakes import FakeLLM

PATIENT = Candidate(
    work_id=1, title="The Silent Patient", authors=["Alex Michaelides"], pages=336, year=2019,
    genres=["psychological thriller"], facets={"darkness": 3, "romance": 1, "pace": "fast"},
    matched=["dark"], description="Alicia Berenson shoots her husband five times, then never "
    "speaks again. A psychotherapist sets out to make her talk.",
)  # fmt: skip
SHARP = Candidate(
    work_id=2, title="Sharp Objects", authors=["Gillian Flynn"], pages=254, year=2006,
    genres=["thriller"], facets={"darkness": 3}, matched=["dark", "under 300 pages"],
    description="A reporter returns to her hometown to cover the murders of two girls.",
)  # fmt: skip
NAMES_PAIRS = [(1, "The Silent Patient"), (2, "Sharp Objects"), (3, "Gone Girl"), (4, "The Road"),
               (5, "The Hunger Games")]  # fmt: skip
NAMES = CatalogNames.from_pairs(
    titles=NAMES_PAIRS,
    authors=[(1, "Alex Michaelides"), (2, "Gillian Flynn"), (3, "Gillian Flynn"),
             (4, "Cormac McCarthy")],
)  # fmt: skip


@pytest.mark.parametrize(
    ("words", "problem"),
    [
        ("Fans of Gone Girl will love this.", "names a title that wasn't given: 'gone girl'"),
        ("As tense as anything by Cormac McCarthy.", "names a author that wasn't given"),
        ("It's on the shelf right now.", "talks about availability: 'on the shelf'"),
        ("You can borrow it today.", "talks about availability: 'can borrow'"),
        ("All 412 pages fly by.", "a number not in the record: 412"),
        ("An award winning debut.", "a claim the record doesn't make: 'award'"),
        ("Now a hit Netflix series.", "a claim the record doesn't make: 'netflix'"),
        ("The tags say it's very dark.", "talks about the data, not the book: 'tags'"),
    ],
)
def test_seeded_errors_are_caught(words: str, problem: str) -> None:
    problems = check(words, [PATIENT], {1}, NAMES)

    assert any(p.startswith(problem) for p in problems), problems


@pytest.mark.parametrize(
    "words",
    [
        "A therapist tries to make a silent woman talk, over 336 tense pages.",
        "Alex Michaelides keeps the twist hidden until the end.",  # its own author
        "Like The Silent Patient, it's about secrets.",  # its own title
        "A long walk down the road of grief.",  # one-word titles ("The Road") are ordinary words
        "Darker than The Hunger Games, as you asked.",  # the reader named it
        "Under 300 pages, as you wanted.",  # the reader's own number
    ],
)
def test_clean_text_passes(words: str) -> None:
    reader = "like the hunger games, under 300 pages"

    assert check(words, [PATIENT], {1}, NAMES, reader) == []


def test_another_shown_book_may_be_named_only_where_allowed() -> None:
    words = "Shorter than Sharp Objects."

    assert check(words, [PATIENT], {1, 2}, NAMES) == []
    assert check(words, [PATIENT], {1}, NAMES) != []


def test_the_schema_only_allows_the_given_ids() -> None:
    schema = reply_schema([1, 2])

    item = schema.model_json_schema()["$defs"]["NarrationItem"]["properties"]["work_id"]
    assert sorted(item["enum"]) == [1, 2]
    with pytest.raises(ValidationError):
        schema.model_validate({"intro": "x", "items": [{"work_id": 3, "why": "invented"}]})


def narration(*items: tuple[int, str], intro: str = "Two dark ones.", follow_up: str = "") -> dict:
    return {
        "intro": intro,
        "items": [{"work_id": i, "why": w} for i, w in items],
        "follow_up": follow_up,
    }


GOOD = narration((1, "A therapist tries to make a silent woman talk."),
                 (2, "A reporter goes home to cover two murders."))  # fmt: skip


def narrate(llm: object, books: list[Candidate] = [PATIENT, SHARP]):  # type: ignore[no-untyped-def]  # noqa: B006
    return Narrator(llm).narrate("recommend", "something dark", books, NAMES, ["dark"])  # type: ignore[arg-type]


def test_a_clean_reply_is_used_as_is() -> None:
    reply = narrate(FakeLLM(GOOD))

    assert (reply.source, reply.attempts, reply.problems) == ("llm", 1, [])
    assert [i.work_id for i in reply.items] == [1, 2]
    assert reply.items[0].why == "A therapist tries to make a silent woman talk."


def test_a_broken_reply_is_retried_with_the_problems_named() -> None:
    bad = narration((1, "Better than Gone Girl."), (2, "A reporter goes home."))
    llm = FakeLLM(bad, GOOD)

    reply = narrate(llm)

    assert (reply.source, reply.attempts) == ("llm", 2)
    assert "gone girl" in llm.calls[1][-1]["content"]  # the retry names what broke
    assert reply.problems == ["1: names a title that wasn't given: 'gone girl'"]


def test_what_still_fails_becomes_a_template_and_the_rest_is_kept() -> None:
    bad = narration((1, "It's available today."), (2, "A reporter goes home to two murders."))

    reply = narrate(FakeLLM(bad, bad))

    assert reply.source == "mixed"
    assert [(i.source, i.why) for i in reply.items] == [
        ("template", "A psychological thriller book (2019, 336 pages); it fits: dark."),
        ("llm", "A reporter goes home to two murders."),
    ]


def test_missing_books_get_a_template_and_extras_are_ignored() -> None:
    partial = narration((2, "A reporter goes home."), (2, "Said twice."))

    reply = narrate(FakeLLM(partial))

    assert [(i.work_id, i.source) for i in reply.items] == [(1, "template"), (2, "llm")]
    assert reply.items[1].why == "A reporter goes home."


def test_no_llm_means_templates() -> None:
    down = narrate(FakeLLM(LLMUnavailable("not running")))
    none = narrate(None)

    assert down.source == none.source == "template"
    assert down.problems == ["llm: not running"]
    assert none.intro == "Here are 2 books that fit."


def test_templates_and_matches() -> None:
    wishes = [
        ("dark", Constraint(field="facet.darkness", op="gte", value=2, strength="soft",
                            source="llm")),
        ("short", Constraint(field="pages", op="lt", value=300, strength="hard", source="rule")),
        ("romantic", Constraint(field="facet.romance", op="gte", value=2, strength="soft",
                                source="llm")),
    ]  # fmt: skip

    assert matched_labels(wishes, {"darkness": 3, "romance": 0}, []) == ["dark", "short"]
    assert templates.compare(PATIENT) == (
        "A psychological thriller book (2019, 336 pages); it fits: dark; darkness very, "
        "romance a little, fast pace."
    )
    assert templates.explain(PATIENT).startswith("Alicia Berenson shoots her husband")


@pytest.mark.parametrize(
    "words",
    [
        "If you loved The Saltwater Detective, try this.",
        "Like the saltwater detective, it is set by the sea.",
        "The next Saltwater Detective book is not here, but this one is close.",
    ],
)
def test_a_book_the_library_lacks_is_never_named(words: str) -> None:
    problems = check(words, [PATIENT], {1}, NAMES, reader="I loved The Saltwater Detective",
                     missing=["The Saltwater Detective"])  # fmt: skip

    assert problems == ["names a book the library doesn't have: 'saltwater detective'"]


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("the third book in the Sundial Wars trilogy", "sundial wars"),
        ("Pemberton Lane Mysteries book 4", "pemberton lane mysteries"),
        ("the sequel to The Iron Psalter", "iron psalter"),
        ("Corin Vale", "corin vale"),
        ("Kestrel", None),  # one word: too common to look for
    ],
)
def test_missing_names_are_looked_for_without_series_words(name: str, key: str | None) -> None:
    assert missing_key(name) == key


@pytest.mark.parametrize(
    ("name", "has"),
    [
        ("gillian flynn thrillers", True),  # an author inside the words
        ("the silent patient alex michaelides", True),  # a title inside the words
        ("the silent pateint", True),  # close spelling
        ("sharp", True),  # "Sharp: Stories" by its main title
        ("1984", True),  # spelled out in the catalog
        ("the six wives of henry the eighth", True),  # "Henry VIII"
        ("1985", False),
        ("The Saltwater Detective", False),
        ("Mara Quill", False),
    ],
)
def test_what_the_catalog_has_something_close_to(name: str, has: bool) -> None:
    names = CatalogNames.from_pairs(
        titles=[
            *NAMES_PAIRS,
            (6, "Sharp: Stories"),
            (7, "Nineteen Eighty-Four"),
            (8, "The Six Wives of Henry VIII"),
        ],
        authors=[(1, "Alex Michaelides"), (2, "Gillian Flynn")],
    )

    assert names.has(name) is has


def test_the_narrator_is_told_what_the_library_lacks() -> None:
    llm = FakeLLM(GOOD)
    Narrator(llm).narrate(  # type: ignore[arg-type]
        "recommend", "I loved The Saltwater Detective and Gone Girl", [PATIENT, SHARP], NAMES,
        [], ["The Saltwater Detective", "Gone Girl"], [3], missing=["The Saltwater Detective"],
    )  # fmt: skip

    prompt = llm.calls[0][-1]["content"]
    assert "Their reference books: Gone Girl\n" in prompt
    assert "Not in this library: The Saltwater Detective." in prompt
