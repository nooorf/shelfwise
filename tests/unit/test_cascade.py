from datetime import date

import pytest

from shelfwise.ingest.genres import GENRES
from shelfwise.llm.client import LLMInvalidOutput, LLMUnavailable
from shelfwise.query.cascade import CascadeParser, Link, strip_words
from shelfwise.query.extract import QueryLLM, build_messages, to_constraints
from shelfwise.query.request import constraint_problems
from tests.fakes import FakeLLM

TODAY = date(2026, 10, 7)


TITLES = {
    "gone girl": Link("Gone Girl", 11),
    "kite runner": Link("The Kite Runner", 13),
    "dune": Link("Dune", 14),
    "graphic novels": Link("Graphic Novels", 15),
}
AUTHORS = {"stephen king": Link("Stephen King"), "dickens": Link("Charles Dickens")}


class FakeLinker:
    """Knows a few catalog spellings; anything else is "not in the catalog"."""

    def title(self, text: str) -> Link | None:
        return next((link for name, link in TITLES.items() if name in text.lower()), None)

    def author(self, text: str) -> Link | None:
        return AUTHORS.get(text.lower())

    def author_in(self, text: str) -> Link | None:
        return next((link for name, link in AUTHORS.items() if name in text.lower()), None)


def parse(query: str, **llm_output: object):  # type: ignore[no-untyped-def]
    llm = FakeLLM(llm_output)
    result = CascadeParser(llm, FakeLinker()).parse(query, TODAY)
    return result.request, llm


def found(request) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        f"{'not ' if c.polarity == 'exclude' else ''}{c.field} {c.op} {c.value} {c.strength}"
        for c in request.constraints
    }


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ({"genres": ["mystery"]}, "genre in ['mystery'] soft"),
        ({"genres": ["mystery"], "genres_strict": True}, "genre in ['mystery'] hard"),
        ({"excluded_genres": ["romance"]}, "not genre in ['romance'] hard"),
        ({"darkness": "dark"}, "facet.darkness gte 2 soft"),
        ({"darkness": "very dark"}, "facet.darkness gte 3 soft"),
        ({"darkness": "light"}, "facet.darkness lte 1 soft"),
        ({"darkness": "not too dark"}, "facet.darkness lte 1 hard"),
        ({"darkness": "not bleak"}, "facet.darkness lte 2 hard"),
        ({"darkness": "darker"}, "facet.darkness shift 1 soft"),
        ({"romance": "none or minor"}, "facet.romance lte 1 hard"),
        ({"romance": "none at all"}, "facet.romance eq 0 hard"),
        ({"romance": "less"}, "facet.romance shift -1 soft"),
        ({"violence": "no gore"}, "facet.violence lte 2 hard"),
        ({"violence": "not too violent"}, "facet.violence lte 1 hard"),
        ({"pace": "fast"}, "facet.pace eq fast soft"),
        ({"supernatural": "excluded"}, "not facet.supernatural eq yes hard"),
        ({"supernatural": "wanted"}, "facet.supernatural eq yes soft"),
        ({"historical_setting": True}, "facet.historical_setting eq yes soft"),
        ({"audience": "ya"}, "facet.audience eq ya soft"),
        ({"fiction": "nonfiction"}, "facet.fiction eq False soft"),
        ({"reading_level": "intro"}, "facet.reading_level eq intro soft"),
        ({"length_change": "shorter"}, "pages shift -1 soft"),
        ({"year_change": "newer"}, "year shift 1 soft"),
        ({"popular": True}, "popular eq True soft"),
        ({"avoid": ["Unreliable  Narrator"]}, "not theme eq unreliable narrator soft"),
    ],
)
def test_form_choices_follow_the_parsing_conventions(form: dict, expected: str) -> None:
    constraints = to_constraints(QueryLLM.model_validate({"intent": "discover", **form}))

    (c,) = constraints
    assert (
        f"{'not ' if c.polarity == 'exclude' else ''}{c.field} {c.op} {c.value} {c.strength}"
        == expected
    )
    assert constraint_problems(c.field, c.op, c.value) == []
    assert c.source == "llm"


def test_schema_only_allows_catalog_genres() -> None:
    schema = QueryLLM.model_json_schema()

    assert schema["properties"]["genres"]["items"]["enum"] == list(GENRES)
    assert QueryLLM.model_validate({"intent": "discover", "genres": ["mystery", "spy"]}).genres == [
        "mystery"
    ]


def test_rules_keep_numbers_and_the_llm_adds_the_rest() -> None:
    request, llm = parse(
        "mystery under 300 pages published after 2015, nothing supernatural",
        intent="discover",
        genres=["mystery"],
        supernatural="excluded",
        semantic_query="mystery nothing supernatural",
    )

    assert found(request) == {
        "pages lt 300 hard",
        "year gt 2015 hard",
        "genre in ['mystery'] soft",
        "not facet.supernatural eq yes hard",
    }
    assert request.semantic_query == "mystery"  # the negated word is stripped
    assert "under 300 pages; published after 2015" in llm.calls[0][1]["content"]  # rule hints


def test_title_lookup_is_linked_and_drops_availability() -> None:
    request, _ = parse(
        "is the kite runner available", intent="lookup", lookup_title="the kite runner"
    )

    assert request.intent == "lookup"
    assert request.lookup is not None and request.lookup.title == "The Kite Runner"
    assert found(request) == set()


def test_author_lookup_keeps_availability() -> None:
    request, _ = parse(
        "stephen king books available now", intent="lookup", lookup_author="stephen king"
    )

    assert request.lookup is not None and request.lookup.author == "Stephen King"
    assert found(request) == {"available_now eq True hard"}


def test_unknown_books_keep_the_written_name() -> None:
    request, _ = parse("do you have harry potter 8", intent="lookup", lookup_title="harry potter 8")

    assert request.lookup is not None and request.lookup.title == "harry potter 8"


def test_seeds_are_linked_with_their_work_ids() -> None:
    request, _ = parse(
        "like gone girl but less romance",
        intent="similar",
        similar_to=["gone girl"],
        romance="less",
        semantic_query="less romance",
    )

    assert request.seed_titles == ["Gone Girl"]
    assert request.seed_work_ids == [11]
    assert found(request) == {"facet.romance shift -1 soft"}
    assert request.semantic_query == ""


@pytest.mark.parametrize(
    ("form", "intent"),
    [
        ({"intent": "lookup"}, "discover"),  # nothing to look up
        ({"intent": "similar"}, "discover"),  # no seed
        ({"intent": "discover", "similar_to": ["gone girl"]}, "similar"),
        ({"intent": "similar", "lookup_title": "gone girl"}, "similar"),  # seed in the wrong slot
    ],
)
def test_intent_is_made_consistent_with_what_was_found(form: dict, intent: str) -> None:
    request, _ = parse("query", **form)

    assert request.intent == intent
    if intent == "similar":
        assert request.seed_titles == ["Gone Girl"]
        assert request.seed_work_ids == [11]
        assert request.lookup is None


def test_isbn_is_always_a_lookup() -> None:
    request, _ = parse("9781250301697", intent="discover")

    assert request.intent == "lookup"
    assert found(request) == {"isbn in ['9781250301697'] hard"}


def test_llm_cannot_override_rule_fields() -> None:
    request, _ = parse("thrillers", intent="discover", genres=["thriller"])
    request_with_rules, _ = parse(
        "something shorter than that, under 200 pages", intent="refine", length_change="shorter"
    )

    assert found(request) == {"genre in ['thriller'] soft"}
    assert found(request_with_rules) == {"pages lt 200 hard", "pages shift -1 soft"}


@pytest.mark.parametrize("error", [LLMUnavailable("down"), LLMInvalidOutput("bad json")])
def test_falls_back_to_rules_when_the_llm_fails(error: Exception) -> None:
    result = CascadeParser(FakeLLM(error), FakeLinker()).parse("horror under 250 pages", TODAY)

    assert not result.used_llm
    assert result.error is not None
    assert found(result.request) == {"pages lt 250 hard"}
    assert result.request.semantic_query == "horror"


def test_empty_semantic_query_falls_back_to_the_rule_residual() -> None:
    request, _ = parse("cozy mystery under 300 pages", intent="discover", genres=["mystery"])

    assert request.semantic_query == "cozy mystery"


# What Qwen3-4B returned for "hi there" (2026-10-08): the whole form, "space" copied from the
# avoid field's description.
FILLED_FORM = {
    "intent": "other",
    "darkness": "light",
    "romance": "wanted",
    "violence": "none at all",
    "pace": "fast",
    "supernatural": "wanted",
    "audience": "ya",
    "fiction": "fiction",
    "reading_level": "advanced",
    "historical_setting": True,
    "length_change": "shorter",
    "year_change": "newer",
    "popular": True,
    "avoid": ["space"],
}


@pytest.mark.parametrize("query", ["hi there", "what time does the library close", "asdfghjkl"])
def test_choices_the_message_gives_no_reason_for_are_dropped(query: str) -> None:
    request, _ = parse(query, **FILLED_FORM)

    assert found(request) == set()


def test_choices_the_message_does_say_are_kept() -> None:
    request, _ = parse(
        "a fast paced cozy fantasy with magic for teens, popular, no romance, shorter than that",
        **FILLED_FORM | {"romance": "none or minor", "darkness": "light", "avoid": []},
    )

    assert found(request) == {
        "genre in ['fantasy'] soft",  # named, so added in code
        "facet.darkness lte 1 soft",
        "facet.romance lte 1 hard",
        "facet.pace eq fast soft",
        "facet.supernatural eq yes soft",
        "facet.audience eq ya soft",
        "popular eq True soft",
        "pages shift -1 soft",
    }


@pytest.mark.parametrize(
    ("query", "form", "expected"),
    [
        # Numbers are the rules' job; a shift needs a comparative.
        ("fantasy under 300 pages", {"length_change": "shorter"},
         {"pages lt 300 hard", "genre in ['fantasy'] soft"}),
        ("dark fantasy from the last decade", {"year_change": "newer"},
         {"year gte 2016 hard", "genre in ['fantasy'] soft"}),
        # A genre the message doesn't name, or names only through a listed synonym.
        ("cozy mystery", {"genres": ["computer science", "mystery"]}, {"genre in ['mystery'] soft"}),
        ("some sci fi", {"genres": ["science fiction"]}, {"genre in ['science fiction'] soft"}),
        ("learn php to build a website", {"genres": ["programming"]},
         {"genre in ['programming'] soft"}),
        # The genre already says it.
        ("romance novels", {"genres": ["romance"], "romance": "wanted"},
         {"genre in ['romance'] soft"}),
        ("historical fiction", {"genres": ["historical fiction"], "historical_setting": True},
         {"genre in ['historical fiction'] soft"}),
        # ... unless an era is named.
        ("historical fiction set in ancient rome",
         {"genres": ["historical fiction"], "historical_setting": True},
         {"genre in ['historical fiction'] soft", "facet.historical_setting eq yes soft"}),
        # Reading-level phrasings from the gold set.
        ("i dont have much previous knowledge of gpus", {"reading_level": "intro"},
         {"facet.reading_level eq intro soft"}),
        ("tdd book for a team thats new to testing", {"reading_level": "intro"},
         {"facet.reading_level eq intro soft"}),
        ("i know some python already", {"reading_level": "intermediate"},
         {"facet.reading_level eq intermediate soft"}),
        ("best sci fi ever", {"popular": True},
         {"popular eq True soft", "genre in ['science fiction'] soft"}),
    ],
)  # fmt: skip
def test_unsupported_shifts_and_genres_are_dropped(
    query: str, form: dict, expected: set[str]
) -> None:
    request, _ = parse(query, intent="discover", **form)

    assert found(request) == expected


@pytest.mark.parametrize(
    ("query", "avoid", "expected"),
    [
        ("an unreliable narrator thriller", ["unreliable narrator"], set()),  # not ruled out
        ("a thriller", ["space"], set()),  # not in the message
        ("not space stuff", ["space"], {"not theme eq space soft"}),
        ("a creepy gothic novel, nothing with vampires", ["vampires"],
         {"not theme eq vampires soft"}),  # a theme, not "nothing supernatural"
        ("stephen king but not horror", ["horror"], {"not genre in ['horror'] hard"}),
        ("a sad book but no war", ["war"], {"not theme eq war soft"}),  # a topic, not a genre
        ("a thriller where no children are harmed", ["children harmed"],
         {"not theme eq children harmed soft"}),  # words spread out in the message
        ("anything except mysteries", ["mysteries"], {"not genre in ['mystery'] hard"}),
        ("the hunger games but less violent", ["violence", "violent"],
         {"facet.violence shift -1 soft"}),
        ("a mystery that isnt gory", ["gory"], {"facet.violence lte 2 hard"}),
        ("books for teens that arent depressing", ["depressing"], {"facet.darkness lte 2 hard"}),
    ],
)  # fmt: skip
def test_avoided_phrases_go_where_parsing_md_puts_them(
    query: str, avoid: list[str], expected: set[str]
) -> None:
    request, _ = parse(query, intent="discover", avoid=avoid)

    named = {f for f in found(request) if f.startswith("genre in")}  # "a thriller": tested above
    assert found(request) - named == expected


@pytest.mark.parametrize(
    ("text", "words", "expected"),
    [
        ("psychological, nothing supernatural", ["supernatural"], "psychological"),
        ("data structures in C++, no self-help", ["self help"], "data structures in C++"),
        ("dogs where the dog dies", ["die", "dies"], "dogs where the dog"),
        ("not just theory, practical", [], "not just theory, practical"),  # nothing negated
        ("cozy fantasy, nothing too dark", ["dark"], "cozy fantasy"),
    ],
)
def test_strip_words(text: str, words: list[str], expected: str) -> None:
    assert strip_words(text, words) == expected


def test_prompt_lists_every_field_and_the_rule_hints() -> None:
    system, user = build_messages("a query", ["under 300 pages"])

    for name in QueryLLM.model_fields:
        assert f"- {name}:" in system["content"]
    assert user["content"].endswith(
        "Already handled (leave out of semantic_query): under 300 pages"
    )


@pytest.mark.parametrize(
    ("query", "title", "author", "constraints"),
    [
        ("do you have gone girl", "Gone Girl", None, set()),
        ("is the kite runner available", "The Kite Runner", None, set()),  # status always shown
        ("do you have dune", "Dune", None, set()),  # one-word title plus a lookup cue
        ("anything by stephen king", None, "Stephen King", set()),
        ("works by dickens published before 1900", None, "Charles Dickens", {"year lt 1900 hard"}),
        ("stephen king books available now", None, "Stephen King", {"available_now eq True hard"}),
        ("9781250301697", None, None, {"isbn in ['9781250301697'] hard"}),
    ],
)
def test_plain_lookups_skip_the_llm(
    query: str, title: str | None, author: str | None, constraints: set[str]
) -> None:
    llm = FakeLLM(LLMUnavailable("must not be called"))
    result = CascadeParser(llm, FakeLinker()).parse(query, TODAY)

    assert result.fast_path and not result.used_llm
    assert llm.calls == []
    assert result.request.intent == "lookup"
    spec = result.request.lookup
    assert (spec.title if spec else None, spec.author if spec else None) == (title, author)
    assert found(result.request) == constraints


@pytest.mark.parametrize(
    "query",
    [
        "something like gone girl but less romance",  # words the title doesn't explain
        "books by stephen king other than it",
        "dune",  # one word, no lookup cue: could be a description
        "graphic novels",  # a title made of genre words
        "a dark fantasy",  # no catalog match at all
    ],
)
def test_anything_more_goes_to_the_llm(query: str) -> None:
    llm = FakeLLM({"intent": "discover"})
    result = CascadeParser(llm, FakeLinker()).parse(query, TODAY)

    assert not result.fast_path
    assert len(llm.calls) == 1


def test_a_negated_mood_beats_a_positive_pick() -> None:
    """2026-10-08, Qwen3-4B on "a cozy fantasy for adults, nothing too dark": darkness "light"
    (from cozy), so "dark" stayed in the search text and pulled "Dark ..." titles up."""
    request, _ = parse(
        "a cozy fantasy for adults, nothing too dark",
        intent="discover",
        genres=["fantasy"],
        darkness="light",
        audience="adult",
        semantic_query="cozy fantasy for adults nothing too dark",
    )

    assert "facet.darkness lte 1 hard" in found(request)
    assert "dark" not in request.semantic_query.split()


@pytest.mark.parametrize(
    ("query", "genres", "strict"),
    [
        ("thrillers i can take home today", ["thriller"], False),
        ("cozy mysteries", ["mystery"], False),
        ("true crime books", ["true crime"], False),  # not also "crime"
        ("manga", ["graphic novels"], False),
        ("a funny book for teens", ["humor"], False),
        ("only mysteries please", ["mystery"], True),
        ("just the best fantasy", ["fantasy"], False),
        ("historical fiction but not about world war 2", ["historical fiction"], False),
        ("childrens books for young adults", [], False),  # audience, never genre
    ],
)
def test_genres_the_message_names(query: str, genres: list[str], strict: bool) -> None:
    from shelfwise.ingest.normalize import fold_text
    from shelfwise.query.extract import named_genres

    assert named_genres(fold_text(query)) == (genres, strict)


def test_named_genres_are_added_but_not_from_book_titles() -> None:
    """Qwen3-4B left `genres` empty for about half the named ones (2026-10-08)."""
    plain, _ = parse("thrillers i can take home today", intent="discover")
    titled, _ = parse("another book like the secret history", intent="similar",
                      similar_to=["the secret history"])  # fmt: skip
    timey, _ = parse("a book about time travel", intent="discover")
    strict, _ = parse("only mysteries please", intent="discover")

    assert "genre in ['thriller'] soft" in found(plain)
    assert not any(c.field == "genre" for c in titled.constraints)
    assert not any(c.field == "genre" for c in timey.constraints)
    assert "genre in ['mystery'] hard" in found(strict)
