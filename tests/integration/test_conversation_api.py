"""A whole conversation through the API: state merging, routing, undo and "new visitor"."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, insert, select, update

from shelfwise.api.main import create_app
from shelfwise.catalog import schema
from shelfwise.catalog.meta import bump_catalog_version
from shelfwise.config import Settings
from shelfwise.conversation.service import ConversationService
from shelfwise.conversation.store import MemorySessionStore
from shelfwise.embed.store import embed_missing, refresh_search_text
from shelfwise.generation.narrate import Narrator
from shelfwise.pipeline import SearchService

from ..fakes import FakeEmbedder, FakeLLM, FakeSpeech, FakeTranscriber, FakeVAD, pcm
from .factories import add_author, add_copy, add_edition, add_work

TODAY = date(2026, 10, 8)
BOOKS = [
    # title, author, genre, year, pages, darkness, popularity
    ("The Silent Patient", "Alex Michaelides", "thriller", 2019, 336, 2, 0.9),
    ("Gone Girl", "Gillian Flynn", "thriller", 2012, 432, 3, 0.8),
    ("Sharp Objects", "Gillian Flynn", "thriller", 2006, 254, 3, 0.7),
    ("The Girl on the Train", "Paula Hawkins", "thriller", 2015, 320, 2, 0.6),
    ("Murder at the Vicarage", "Agatha Christie", "mystery", 1930, 288, 0, 0.5),
    ("The Thursday Murder Club", "Richard Osman", "mystery", 2020, 382, 1, 0.4),
]


@pytest.fixture
def catalog(conn: Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    authors: dict[str, int] = {}
    for title, author, genre, year, pages, darkness, popularity in BOOKS:
        work_id = add_work(conn, title, first_pub_year=year, genres=[genre])
        mood = "a dark psychological thriller" if genre == "thriller" else "a cozy village mystery"
        conn.execute(
            update(schema.work)
            .where(schema.work.c.work_id == work_id)
            .values(description=f"{title}: {mood}", popularity=popularity)
        )
        add_copy(conn, add_edition(conn, work_id, pages=pages, isbn13=None), "available")
        if author not in authors:
            authors[author] = add_author(conn, author)
        conn.execute(insert(schema.work_author).values(work_id=work_id, author_id=authors[author]))
        conn.execute(
            insert(schema.work_facets).values(work_id=work_id, darkness=darkness, source="human")
        )
        ids[title] = work_id
    refresh_search_text(conn)
    bump_catalog_version(conn)
    return ids


# What the LLM answers, turn by turn (FakeLLM hands them out in order).
FORMS: list[Any] = [
    {"intent": "discover", "genres": ["thriller"], "semantic_query": "psychological thrillers"},
    {"intent": "refine", "darkness": "darker"},
    {"intent": "refine"},  # "under 300 pages": the rules take the number
    {"intent": "explain"},
    {"intent": "discover", "darkness": "light", "semantic_query": "something cozy"},
    {"intent": "other"},
]


class NarratingLLM:
    """Writes a note for whichever books it is given (they're in the schema's enum)."""

    model = "fake-narrator"

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.delay_s = delay_s

    def chat_structured(self, messages, schema, **kwargs):  # type: ignore[no-untyped-def]
        import time

        from shelfwise.llm.client import GenerationStats, StructuredResult

        self.calls.append(messages)
        time.sleep(self.delay_s)
        prop = schema.model_json_schema()["$defs"]["NarrationItem"]["properties"]["work_id"]
        ids = prop.get("enum") or [prop["const"]]  # one book: a const, not an enum
        value = {"intro": "A few picks.", "items": [{"work_id": i, "why": "A gripping story."}
                                                    for i in ids]}  # fmt: skip
        stats = GenerationStats(self.model, 100, 40, 50.0, 0.0, 1)
        return StructuredResult(schema.model_validate(value), stats)


@contextmanager
def make_client(
    conn: Connection, forms: list[Any], narrator: NarratingLLM | None = None,
    speech: FakeSpeech | None = None, listening: tuple[Any, Any] | None = None,
) -> Iterator[TestClient]:  # fmt: skip
    embedder = FakeEmbedder()
    embed_missing(conn, embedder)
    search = SearchService(embedder=embedder, today=lambda: TODAY, llm=FakeLLM(*forms))
    conversation = ConversationService(
        search,
        MemorySessionStore(ttl_s=1800),
        now=lambda: datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        narrator=Narrator(narrator or NarratingLLM()),
        speech=speech,
        listening=listening,
    )
    app = create_app(
        Settings(profile="cpu", log_json=False), service=search, conversation=conversation
    )

    def test_connection() -> Iterator[Connection]:
        yield conn

    app.dependency_overrides[app.state.resources.connection] = test_connection
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client(conn: Connection, catalog: dict[str, int]) -> Iterator[TestClient]:
    with make_client(conn, FORMS) as test_client:
        yield test_client


def say(client: TestClient, session: str, message: str) -> dict[str, Any]:
    response = client.post(f"/api/v1/sessions/{session}/turns", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def chips(body: dict[str, Any]) -> set[str]:
    return {f"{c['field']} {c['op']} {c['value']}" for c in body["chips"]}


def test_a_conversation_refines_explains_resets_and_undoes(client: TestClient) -> None:
    created = client.post("/api/v1/sessions")
    assert created.status_code == 201
    session = created.json()["session_id"]

    one = say(client, session, "psychological thrillers")
    assert (one["kind"], one["route"], one["parser"]) == ("new_search", "search", "cascade")
    assert one["reply"]["source"] == "llm"
    assert [i["work_id"] for i in one["reply"]["items"]] == [r["work_id"] for r in one["results"]]
    assert {r["title"] for r in one["results"][:4]} == {
        t for t, _, g, *_ in BOOKS if g == "thriller"
    }

    two = say(client, session, "something darker")
    assert two["kind"] == "refine"
    darker = next(c for c in two["chips"] if c["field"] == "facet.darkness")
    assert (darker["label"], darker["op"], darker["strength"]) == ("darker", "gte", "soft")

    three = say(client, session, "under 300 pages")
    assert "pages lt 300" in chips(three)
    assert {r["title"] for r in three["results"]} == {"Sharp Objects", "Murder at the Vicarage"}
    assert three["semantic_query"] == "psychological thrillers"  # the topic carried over

    four = say(client, session, "tell me about the second one")
    second = three["results"][1]["work_id"]
    assert (four["route"], [r["work_id"] for r in four["results"]]) == ("explain", [second])
    assert str(second) in four["facets"]
    assert chips(four) == chips(three)  # explaining changes nothing

    five = say(client, session, "actually something cozy")
    assert (five["kind"], five["can_undo"]) == ("new_topic", True)
    assert five["notes"][0] == "New search."
    assert chips(five) == {"facet.darkness lte 1"}

    undone = client.post(f"/api/v1/sessions/{session}/undo").json()
    assert (undone["kind"], undone["route"]) == ("undo", "search")
    assert undone["semantic_query"] == "psychological thrillers"
    assert "pages lt 300" in chips(undone)
    assert not undone["can_undo"]

    hello = say(client, session, "hi")
    assert (hello["route"], hello["results"], hello["reply"]) == ("chat", [], None)

    assert client.delete(f"/api/v1/sessions/{session}").status_code == 204
    gone = client.post(f"/api/v1/sessions/{session}/turns", json={"message": "hello again"})
    assert gone.status_code == 404


def test_unknown_sessions_are_404(client: TestClient) -> None:
    response = client.post("/api/v1/sessions/nope/turns", json={"message": "hi"})

    assert response.status_code == 404


def test_surprise_and_compare(conn: Connection, catalog: dict[str, int]) -> None:
    forms = [
        {"intent": "discover", "genres": ["thriller"], "semantic_query": "thrillers"},
        {"intent": "compare"},
        {"intent": "surprise"},
    ]
    with make_client(conn, forms) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]
        first = client.post(
            f"/api/v1/sessions/{session}/turns", json={"message": "thrillers", "limit": 2}
        ).json()
        shown = [r["work_id"] for r in first["results"]]

        compare = say(client, session, "which of these is darker")
        surprise = say(client, session, "surprise me")

    assert compare["route"] == "compare"
    assert [r["work_id"] for r in compare["results"]] == shown  # no target named: all shown
    assert set(compare["facets"]) == {str(w) for w in shown}
    assert surprise["route"] == "surprise"
    picks = [r["work_id"] for r in surprise["results"]]
    assert picks and len(picks) <= 3
    assert not set(picks) & set(shown)  # something not seen yet
    assert all(r["availability"]["state"] == "available" for r in surprise["results"])


def test_narration_can_be_skipped(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]

    body = client.post(
        f"/api/v1/sessions/{session}/turns",
        json={"message": "psychological thrillers", "narrate": False},
    ).json()

    assert body["results"] and body["reply"] is None
    assert body["timings_ms"]["narrate"] == 0.0


def lend(conn: Connection, work_id: int, due: date) -> None:
    editions = select(schema.edition.c.edition_id).where(schema.edition.c.work_id == work_id)
    conn.execute(
        update(schema.copy)
        .where(schema.copy.c.edition_id.in_(editions))
        .values(status="on_loan", due_date=due)
    )


def test_no_match_offers_relaxations_and_remembers_the_answer(
    conn: Connection, catalog: dict[str, int]
) -> None:
    lend(conn, catalog["The Silent Patient"], date(2026, 10, 20))
    lend(conn, catalog["The Thursday Murder Club"], date(2026, 10, 15))
    forms = [{"intent": "discover", "semantic_query": "something"}]
    query = "something available now published after 2018"
    with make_client(conn, forms) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]

        empty = say(client, session, query)
        picked = say(client, session, "the second one")
        again = say(client, session, query)
        refused = say(client, session, "no thanks")
        last = say(client, session, query)

    # The 2019 and 2020 books are both out; everything else is older.
    assert empty["results"] == []
    assert [(r["drop"], r["count"], r["earliest_due"]) for r in empty["relaxations"]] == [
        ("published after 2018", 4, None),
        ("available now", 2, "2026-10-15"),
    ]
    assert empty["notes"][-1].endswith("the earliest due back Thu 15 Oct. Which should I drop?")

    assert (picked["kind"], picked["route"]) == ("relax", "search")
    assert picked["notes"][0] == 'Dropped "available now".'
    assert {r["title"] for r in picked["results"]} == {
        "The Silent Patient", "The Thursday Murder Club"
    }  # fmt: skip

    assert again["results"] == [] and again["relaxations"]
    assert (refused["kind"], refused["route"]) == ("relax", "chat")
    assert last["relaxations"] == []  # refused once, never offered again
    assert last["notes"][-1] == "Nothing in the catalog matches that."


def events_until_done(ws: Any) -> list[dict[str, Any]]:
    events = []
    while True:
        events.append(ws.receive_json())
        if events[-1]["type"] in ("done", "error"):
            return events


def test_the_socket_sends_cards_first_then_the_reply(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]

    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_json({"type": "text", "text": "psychological thrillers"})
        narrated = events_until_done(ws)
        ws.send_json({"type": "text", "text": "something darker", "narrate": False})
        quiet = events_until_done(ws)

    assert [e["type"] for e in narrated] == ["turn", "reply", "done"]
    turn, reply = narrated[0], narrated[1]
    assert turn["results"] and turn["reply"] is None  # cards don't wait for the LLM
    assert [i["work_id"] for i in reply["reply"]["items"]] == [
        r["work_id"] for r in turn["results"]
    ]
    assert [e["type"] for e in quiet] == ["turn", "done"]
    assert quiet[0]["kind"] == "refine"


def test_a_new_message_cancels_the_running_narration(
    conn: Connection, catalog: dict[str, int]
) -> None:
    forms = [{"intent": "discover", "semantic_query": "thrillers"},
             {"intent": "discover", "semantic_query": "mysteries"}]  # fmt: skip
    with make_client(conn, forms, NarratingLLM(delay_s=0.5)) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
            ws.send_json({"type": "text", "text": "thrillers"})
            first = ws.receive_json()
            ws.send_json({"type": "text", "text": "actually, mysteries"})
            rest = events_until_done(ws)

    assert first["type"] == "turn" and first["turn"] == 1
    assert [(e["type"], e["turn"]) for e in rest] == [
        ("cancelled", 1), ("turn", 2), ("reply", 2), ("done", 2)
    ]  # fmt: skip


def test_unknown_sessions_are_refused_on_the_socket(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/sessions/nope/stream") as ws:
        assert ws.receive_json()["type"] == "error"


def test_availability_is_read_live_when_a_shown_book_comes_up_again(
    conn: Connection, catalog: dict[str, int]
) -> None:
    forms = [{"intent": "discover", "semantic_query": "mysteries"}, {"intent": "explain"}]
    with make_client(conn, forms) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]
        shown = say(client, session, "mysteries")
        second = shown["results"][1]
        lend(conn, second["work_id"], date(2026, 10, 20))  # borrowed between the two turns
        asked = say(client, session, "is the second one available")

    assert second["availability"]["state"] == "available"
    assert asked["route"] == "explain"
    assert asked["results"][0]["availability"]["state"] == "borrowed"
    assert asked["results"][0]["availability"]["next_due"] == "2026-10-20"


def test_removing_a_chip_searches_again_without_it(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    say(client, session, "psychological thrillers")
    narrowed = say(client, session, "under 300 pages")
    chip = next(c for c in narrowed["chips"] if c["field"] == "pages")

    url = f"/api/v1/sessions/{session}/chips/remove"
    removed = client.post(url, json={"field": "pages", "label": chip["label"]}).json()
    again = client.post(url, json={"field": "pages", "label": chip["label"]}).json()

    assert (removed["kind"], removed["route"]) == ("remove", "search")
    assert "pages lt 300" not in chips(removed)
    assert len(removed["results"]) > len(narrowed["results"])
    assert removed["semantic_query"] == "psychological thrillers"
    assert (again["route"], again["notes"]) == ("chat", ["That filter is already gone."])


def test_a_chip_can_be_removed_over_the_socket(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    narrowed = say(client, session, "psychological thrillers under 300 pages")
    chip = next(c for c in narrowed["chips"] if c["field"] == "pages")
    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_json({"type": "remove_chip", "field": "pages", "label": chip["label"],
                      "narrate": False})  # fmt: skip
        events = events_until_done(ws)

    assert [e["type"] for e in events] == ["turn", "done"]
    assert events[0]["kind"] == "remove" and "pages lt 300" not in chips(events[0])


def test_more_and_less_like_a_shown_book(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    shown = say(client, session, "psychological thrillers")
    first = shown["results"][0]
    url = f"/api/v1/sessions/{session}/feedback"

    more = client.post(url, json={"work_id": first["work_id"], "more": True}).json()
    assert (more["kind"], more["route"], more["seed_titles"]) == (
        "more_like",
        "search",
        [first["title"]],
    )
    assert first["work_id"] not in {r["work_id"] for r in more["results"]}  # the seed itself

    other = more["results"][0]
    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_json({"type": "less_like", "work_id": other["work_id"], "narrate": False})
        events = events_until_done(ws)
    less = events[0]
    assert [e["type"] for e in events] == ["turn", "done"]
    assert less["kind"] == "less_like" and less["notes"] == [f"Fewer like {other['title']}."]
    assert other["work_id"] not in {r["work_id"] for r in less["results"]}


def test_a_chip_switches_between_must_and_preferred(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    say(client, session, "psychological thrillers")
    narrowed = say(client, session, "under 300 pages")
    chip = next(c for c in narrowed["chips"] if c["field"] == "pages")
    assert (chip["strength"], chip["switchable"]) == ("hard", True)

    url = f"/api/v1/sessions/{session}/chips/strength"
    body = {"field": "pages", "label": chip["label"]}
    preferred = client.post(url, json=body | {"strength": "soft"}).json()
    must = client.post(url, json=body | {"strength": "hard"}).json()

    assert (preferred["kind"], preferred["route"]) == ("strength", "search")
    assert [c["strength"] for c in preferred["chips"] if c["field"] == "pages"] == ["soft"]
    assert len(preferred["results"]) > len(narrowed["results"])
    assert [r["work_id"] for r in must["results"]] == [r["work_id"] for r in narrowed["results"]]


def test_a_chip_that_only_filters_stays_a_must(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    narrowed = say(client, session, "psychological thrillers available now")
    chip = next(c for c in narrowed["chips"] if c["field"] == "available_now")
    assert chip["switchable"] is False

    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_json({"type": "chip_strength", "field": "available_now", "label": chip["label"],
                      "strength": "soft", "narrate": False})  # fmt: skip
        events = events_until_done(ws)

    assert [e["type"] for e in events] == ["turn", "done"]
    assert events[0]["route"] == "chat"
    assert events[0]["notes"] == [f'"{chip["label"]}" can only be a must.']
    assert chips(events[0]) == chips(narrowed)


def test_the_surprise_button_picks_unseen_books_on_the_shelf(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    first = client.post(
        f"/api/v1/sessions/{session}/turns", json={"message": "thrillers", "limit": 2}
    ).json()
    shown = {r["work_id"] for r in first["results"]}
    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_json({"type": "surprise", "narrate": False})
        events = events_until_done(ws)

    assert [e["type"] for e in events] == ["turn", "done"]
    turn = events[0]
    assert (turn["kind"], turn["route"]) == ("surprise", "surprise")
    picks = {r["work_id"] for r in turn["results"]}
    assert 0 < len(picks) <= 3 and not picks & shown
    assert all(r["availability"]["state"] == "available" for r in turn["results"])
    assert turn["semantic_query"] == first["semantic_query"]  # the search is kept


def test_the_surprise_button_says_when_nothing_fits(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    say(client, session, "books from 1066")
    body = client.post(f"/api/v1/sessions/{session}/surprise", json={"narrate": False}).json()

    assert body["results"] == [] and body["notes"] == [
        "Nothing on the shelf right now fits your filters. Try removing one."
    ]


def test_genres_for_explore(client: TestClient) -> None:
    assert client.get("/api/v1/genres").json() == [
        {"name": "thriller", "books": 4},
        {"name": "mystery", "books": 2},
    ]


def test_explore_browses_a_genre_on_the_shelf_first_then_by_popularity(
    conn: Connection, client: TestClient, catalog: dict[str, int]
) -> None:
    lend(conn, catalog["The Silent Patient"], date(2026, 10, 20))  # the most borrowed is out
    session = client.post("/api/v1/sessions").json()["session_id"]
    url = f"/api/v1/sessions/{session}/explore"

    body = client.post(url, json={"genre": "thriller", "narrate": False}).json()

    assert (body["kind"], body["route"], body["system"]) == ("new_search", "search", "browse")
    assert [r["title"] for r in body["results"]] == [
        "Gone Girl", "Sharp Objects", "The Girl on the Train", "The Silent Patient",
    ]  # fmt: skip
    assert chips(body) == {"genre in ['thriller']"} and body["semantic_query"] == ""


def test_filters_narrow_an_explore_search_and_explore_again_can_be_undone(
    conn: Connection, catalog: dict[str, int]
) -> None:
    with make_client(conn, [{"intent": "refine"}]) as client:  # "under 260 pages"
        session = client.post("/api/v1/sessions").json()["session_id"]
        base = f"/api/v1/sessions/{session}"
        client.post(f"{base}/explore", json={"genre": "thriller", "narrate": False})

        short = client.post(f"{base}/filters", json={"pages_max": 300, "available_now": True,
                                                     "narrate": False}).json()  # fmt: skip
        typed = say(client, session, "under 260 pages")  # a typed refinement keeps browsing
        other = client.post(f"{base}/explore", json={"genre": "mystery", "narrate": False})
        back = client.post(f"{base}/undo").json()
        empty_form = client.post(f"{base}/filters", json={})

    assert (short["kind"], short["system"]) == ("refine", "browse")
    assert [r["title"] for r in short["results"]] == ["Sharp Objects"]
    assert chips(short) == {"genre in ['thriller']", "pages lte 300", "available_now eq True"}
    assert typed["system"] == "browse" and "pages lt 260" in chips(typed)
    other = other.json()
    assert other["kind"] == "new_topic" and other["notes"] == ["New search (kept: available now)."]
    assert {r["title"] for r in other["results"]} == {
        "Murder at the Vicarage", "The Thursday Murder Club"
    }  # fmt: skip
    assert other["can_undo"] and "genre in ['thriller']" in chips(back)
    assert empty_form.status_code == 422


def test_the_inspector_shows_each_stage_of_a_turn(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    body = say(client, session, "psychological thrillers")
    inspector = body["inspector"]

    assert inspector["parsed"]["semantic_query"] == "psychological thrillers"
    assert inspector["searched"]["constraints"] == inspector["parsed"]["constraints"]
    stages = {s["name"]: s for s in inspector["stages"]}
    assert list(stages) == ["filter", "bm25", "dense", "fused", "final"]
    assert stages["filter"]["count"] == 6 and stages["filter"]["top"] == []  # no musts
    assert all(h["score"] is not None for h in stages["dense"]["top"])
    final = stages["final"]["top"]
    assert [h["work_id"] for h in final] == [r["work_id"] for r in body["results"]]
    assert [h["title"] for h in final] == [r["title"] for r in body["results"]]

    browse = client.post(f"/api/v1/sessions/{session}/explore",
                         json={"genre": "mystery", "narrate": False}).json()["inspector"]  # fmt: skip
    assert browse["parsed"] is None and browse["searched"]["semantic_query"] == ""
    assert [s["name"] for s in browse["stages"]] == ["filter", "final"]


def test_speech_reads_the_reply_aloud_sentence_by_sentence(
    conn: Connection, catalog: dict[str, int]
) -> None:
    import base64
    import io
    import wave

    speech = FakeSpeech()
    with make_client(conn, FORMS, speech=speech) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
            ws.send_json({"type": "speak", "on": True})
            assert ws.receive_json() == {"type": "speak", "on": True}
            ws.send_json({"type": "text", "text": "psychological thrillers"})
            events = events_until_done(ws)
        clip = client.post("/api/v1/speech", json={"text": "Hello there."})

    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["turn", "reply"] and kinds[-1] == "done"
    audio = [e for e in events if e["type"] == "audio"]
    assert [a["seq"] for a in audio] == list(range(len(audio))) and audio
    assert audio[0]["text"].startswith("A few picks.")  # the reply's intro first
    assert [a["text"] for a in audio] == speech.said[: len(audio)]
    with wave.open(io.BytesIO(base64.b64decode(audio[0]["wav"]))) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (8000, 2, 1)
    assert clip.status_code == 200 and clip.headers["content-type"] == "audio/wav"


def test_without_a_speech_model_speak_stays_off(client: TestClient) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_json({"type": "speak", "on": True})
        assert ws.receive_json() == {"type": "speak", "on": False}
        ws.send_json({"type": "text", "text": "psychological thrillers"})
        events = events_until_done(ws)

    assert "audio" not in {e["type"] for e in events}
    assert client.post("/api/v1/speech", json={"text": "Hello."}).status_code == 503


def test_a_spoken_question_is_transcribed_and_answered(
    conn: Connection, catalog: dict[str, int]
) -> None:
    stt = FakeTranscriber("psychological thrillers")
    with make_client(conn, FORMS, listening=(FakeVAD(), stt)) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
            ws.send_json({"type": "listen", "on": True})
            assert ws.receive_json() == {"type": "listening", "on": True}
            audio = pcm(("silence", 0.5), ("tone", 1.0), ("silence", 1.0))
            for i in range(0, len(audio), 1024):  # 32 ms frames, as the browser sends
                ws.send_bytes(audio[i : i + 1024])
            events = events_until_done(ws)

    kinds = [e["type"] for e in events]
    assert kinds[:4] == ["speech_start", "listening", "transcript", "turn"]
    assert events[1] == {"type": "listening", "on": False, "reason": "heard"}
    assert events[2] == {"type": "transcript", "text": "psychological thrillers", "fixed": []}
    assert events[3]["semantic_query"] == "psychological thrillers" and events[3]["results"]
    assert stt.heard == [pytest.approx(1.8, abs=0.1)]  # pre-roll + speech + 600 ms


def test_listening_is_refused_without_models_and_stray_audio_is_ignored(
    client: TestClient,
) -> None:
    session = client.post("/api/v1/sessions").json()["session_id"]
    with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
        ws.send_bytes(pcm(("tone", 0.1)))  # not listening: dropped
        ws.send_json({"type": "listen", "on": True})
        assert ws.receive_json() == {"type": "listening", "on": False, "reason": "unavailable"}
        ws.send_text("not json")
        assert ws.receive_json() == {"type": "error", "message": "not JSON"}


def test_a_misheard_author_is_respelled_from_the_catalog(
    conn: Connection, catalog: dict[str, int]
) -> None:
    stt = FakeTranscriber("anything else by jillian flynn?")
    with make_client(conn, FORMS, listening=(FakeVAD(), stt)) as client:
        session = client.post("/api/v1/sessions").json()["session_id"]
        with client.websocket_connect(f"/api/v1/sessions/{session}/stream") as ws:
            ws.send_json({"type": "listen", "on": True})
            ws.receive_json()
            ws.send_bytes(pcm(("tone", 0.5), ("silence", 1.0)))
            events = events_until_done(ws)

    transcript = next(e for e in events if e["type"] == "transcript")
    assert transcript["text"] == "anything else by Gillian Flynn?"
    assert transcript["fixed"] == [{"heard": "jillian flynn", "catalog": "Gillian Flynn"}]
