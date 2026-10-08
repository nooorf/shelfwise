"""A whole conversation through the API: state merging, routing, undo and "new visitor"."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, insert, update

from shelfwise.api.main import create_app
from shelfwise.catalog import schema
from shelfwise.catalog.meta import bump_catalog_version
from shelfwise.config import Settings
from shelfwise.conversation.service import ConversationService
from shelfwise.conversation.store import MemorySessionStore
from shelfwise.embed.store import embed_missing, refresh_search_text
from shelfwise.generation.narrate import Narrator
from shelfwise.pipeline import SearchService

from ..fakes import FakeEmbedder, FakeLLM
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

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat_structured(self, messages, schema, **kwargs):  # type: ignore[no-untyped-def]
        from shelfwise.llm.client import GenerationStats, StructuredResult

        self.calls.append(messages)
        prop = schema.model_json_schema()["$defs"]["NarrationItem"]["properties"]["work_id"]
        ids = prop.get("enum") or [prop["const"]]  # one book: a const, not an enum
        value = {"intro": "A few picks.", "items": [{"work_id": i, "why": "A gripping story."}
                                                    for i in ids]}  # fmt: skip
        stats = GenerationStats(self.model, 100, 40, 50.0, 0.0, 1)
        return StructuredResult(schema.model_validate(value), stats)


@contextmanager
def make_client(conn: Connection, forms: list[Any]) -> Iterator[TestClient]:
    embedder = FakeEmbedder()
    embed_missing(conn, embedder)
    search = SearchService(embedder=embedder, today=lambda: TODAY, llm=FakeLLM(*forms))
    conversation = ConversationService(
        search,
        MemorySessionStore(ttl_s=1800),
        now=lambda: datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        narrator=Narrator(NarratingLLM()),
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
