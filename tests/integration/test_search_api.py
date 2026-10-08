from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, insert, update

from shelfwise.api.main import create_app
from shelfwise.catalog import schema
from shelfwise.catalog.meta import bump_catalog_version
from shelfwise.config import Settings
from shelfwise.embed.store import embed_missing, refresh_search_text
from shelfwise.llm.client import LLMUnavailable
from shelfwise.pipeline import SearchRequest, SearchService
from shelfwise.ranking.rerank import CachedReranker

from ..fakes import FakeEmbedder, FakeLLM, FakeReranker
from .factories import add_author, add_copy, add_edition, add_work

TODAY = date(2026, 10, 7)
BOOKS = [
    # title, author, year, pages, copy status, isbn
    ("The Silent Patient", "Alex Michaelides", 2019, 336, "available", "9781250301697"),
    ("Gone Girl", "Gillian Flynn", 2012, 432, "on_loan", "9780307588371"),
    ("Sharp Objects", "Gillian Flynn", 2006, 254, "available", "9780307341556"),
]


@pytest.fixture
def catalog(conn: Connection) -> dict[str, int]:
    ids, authors = {}, {}
    for title, author, year, pages, status, isbn in BOOKS:
        work_id = add_work(conn, title, first_pub_year=year, genres=["thriller"])
        conn.execute(
            update(schema.work)
            .where(schema.work.c.work_id == work_id)
            .values(description=f"{title}: a dark psychological thriller")
        )
        copy_id = add_copy(
            conn, add_edition(conn, work_id, pages=pages, isbn13=isbn), status,
            due_date=date(2026, 10, 10) if status == "on_loan" else None,
        )  # fmt: skip
        conn.execute(
            update(schema.copy)
            .where(schema.copy.c.copy_id == copy_id)
            .values(floor="2", call_number=f"FIC {author.split()[-1][:3].upper()}")
        )
        if author not in authors:
            authors[author] = add_author(conn, author)
        conn.execute(insert(schema.work_author).values(work_id=work_id, author_id=authors[author]))
        ids[title] = work_id
    bump_catalog_version(conn)
    return ids


def search(conn: Connection, query: str, service: SearchService | None = None, limit: int = 5):
    service = service or SearchService(today=lambda: TODAY)
    return service.search(conn, SearchRequest(query=query, limit=limit))


def test_lookup_returns_the_book_with_live_availability_and_location(
    conn: Connection, catalog: dict[str, int]
) -> None:
    response = search(conn, "do you have the silent patient")

    top = response.results[0]
    assert top.title == "The Silent Patient" and top.authors == ["Alex Michaelides"]
    assert top.work_key == "9781250301697"
    assert top.availability.state == "available"
    assert top.availability.location is not None
    assert (top.availability.location.floor, top.availability.location.call_number) == (
        "2", "FIC MIC",
    )  # fmt: skip
    assert response.system == "bm25_lookup"  # no embedder given


def test_borrowed_book_reports_its_due_date(conn: Connection, catalog: dict[str, int]) -> None:
    top = search(conn, "gone girl").results[0]

    assert top.title == "Gone Girl"
    assert top.availability.state == "due_soon"
    assert top.availability.next_due == date(2026, 10, 10)


def test_hard_filters_are_parsed_shown_and_respected(
    conn: Connection, catalog: dict[str, int]
) -> None:
    response = search(conn, "dark thriller under 300 pages")

    assert [r.title for r in response.results] == ["Sharp Objects"]
    assert [(c.field, c.op, c.value, c.span) for c in response.constraints] == [
        ("pages", "lt", 300, "under 300 pages")
    ]
    assert "300" not in response.residual


def test_no_match_suggests_which_filter_to_drop(conn: Connection, catalog: dict[str, int]) -> None:
    response = search(conn, "thriller under 100 pages")

    assert response.results == []
    assert [(r.drop, r.count) for r in response.relaxations] == [("under 100 pages", 3)]


def test_contradictory_filters_return_an_explanation(
    conn: Connection, catalog: dict[str, int]
) -> None:
    response = search(conn, "books over 500 pages but under 300 pages")

    assert response.results == [] and response.relaxations == []
    assert response.contradictions and "pages" in response.contradictions[0]


def test_index_is_rebuilt_when_the_catalog_changes(
    conn: Connection, catalog: dict[str, int]
) -> None:
    service = SearchService(today=lambda: TODAY)
    assert search(conn, "rebecca", service).results == []

    work_id = add_work(conn, "Rebecca", first_pub_year=1938)
    add_copy(conn, add_edition(conn, work_id), "available")
    bump_catalog_version(conn)

    assert [r.title for r in search(conn, "rebecca", service).results][:1] == ["Rebecca"]


def test_hybrid_search_when_an_embedder_is_loaded(
    conn: Connection, catalog: dict[str, int]
) -> None:
    embedder = FakeEmbedder()
    refresh_search_text(conn)
    embed_missing(conn, embedder)
    service = SearchService(embedder=embedder, today=lambda: TODAY)

    response = search(conn, "psychological thriller", service)

    assert response.system == "hybrid_lookup"
    assert {r.title for r in response.results} == {t for t, *_ in BOOKS}


def test_reranker_reorders_hybrid_results_when_configured(
    conn: Connection, catalog: dict[str, int]
) -> None:
    embedder = FakeEmbedder()
    refresh_search_text(conn)
    embed_missing(conn, embedder)
    inner = FakeReranker()
    service = SearchService(embedder=embedder, today=lambda: TODAY, reranker=CachedReranker(inner))

    response = search(conn, "something like sharp objects", service, limit=3)

    assert response.system == "hybrid_rerank"
    assert response.results[0].title == "Sharp Objects"  # also a title lookup: stays first
    assert inner.calls and inner.calls[0][0] == "something like sharp objects"
    assert all("Title:" in doc for doc in inner.calls[0][1])  # it reads each book's search text


def llm_service(conn: Connection, llm: FakeLLM) -> SearchService:
    embedder = FakeEmbedder()
    refresh_search_text(conn)
    embed_missing(conn, embedder)
    return SearchService(embedder=embedder, today=lambda: TODAY, llm=llm)


def test_the_llm_parse_drives_the_search(conn: Connection, catalog: dict[str, int]) -> None:
    llm = FakeLLM({
        "intent": "discover",
        "genres": ["thriller"],
        "supernatural": "excluded",
        "semantic_query": "a dark thriller nothing supernatural",
    })  # fmt: skip

    response = search(
        conn, "a dark thriller under 300 pages, nothing supernatural", llm_service(conn, llm)
    )

    assert (response.parser, response.system, response.parse_error) == (
        "cascade", "parsed_hybrid", None
    )  # fmt: skip
    assert response.intent == "discover"
    assert response.residual == "a dark thriller"  # the negated word is stripped
    assert {f"{c.polarity} {c.field} {c.op} {c.value}" for c in response.constraints} == {
        "include pages lt 300",
        "include genre in ['thriller']",
        "exclude facet.supernatural eq yes",
    }
    assert [r.title for r in response.results] == ["Sharp Objects"]  # the only one < 300 pp


def test_plain_lookups_skip_the_llm(conn: Connection, catalog: dict[str, int]) -> None:
    llm = FakeLLM(LLMUnavailable("must not be called"))

    response = search(conn, "do you have gone girl", llm_service(conn, llm))

    assert llm.calls == []
    assert (response.parser, response.intent) == ("cascade", "lookup")
    assert response.lookup is not None and response.lookup.title == "Gone Girl"
    assert response.results[0].title == "Gone Girl"


def test_falls_back_to_the_rules_when_the_llm_is_down(
    conn: Connection, catalog: dict[str, int]
) -> None:
    response = search(
        conn, "a psychological thriller", llm_service(conn, FakeLLM(LLMUnavailable("down")))
    )

    assert (response.parser, response.system) == ("rules", "hybrid_lookup")
    assert response.parse_error == "down"
    assert {r.title for r in response.results} == {t for t, *_ in BOOKS}


@pytest.fixture
def client(conn: Connection, catalog: dict[str, int]) -> Iterator[TestClient]:
    service = SearchService(today=lambda: TODAY)
    app = create_app(Settings(profile="cpu", log_json=False), service=service)
    resources = app.state.resources

    def test_connection() -> Iterator[Connection]:
        yield conn  # the test's transaction, so the fixture data is visible

    app.dependency_overrides[resources.connection] = test_connection
    with TestClient(app) as test_client:
        yield test_client


def test_search_endpoint(client: TestClient) -> None:
    response = client.post("/api/v1/search", json={"query": "anything by gillian flynn"})

    assert response.status_code == 200
    body = response.json()
    assert [r["title"] for r in body["results"]][:2] == ["Gone Girl", "Sharp Objects"]
    assert body["results"][0]["availability"]["state"] == "due_soon"
    assert set(body["timings_ms"]) >= {"parse", "retrieve", "details", "total"}


@pytest.mark.parametrize("payload", [{"query": ""}, {"query": "x", "limit": 0}, {}])
def test_invalid_requests_are_rejected(client: TestClient, payload: dict[str, object]) -> None:
    assert client.post("/api/v1/search", json=payload).status_code == 422


def test_book_endpoint_shows_the_record_behind_a_card(
    client: TestClient, conn: Connection, catalog: dict[str, int]
) -> None:
    work_id = catalog["Gone Girl"]
    edition = conn.execute(
        schema.edition.select().where(schema.edition.c.work_id == work_id)
    ).first()
    assert edition is not None
    add_copy(conn, edition.edition_id, "available")
    add_copy(conn, edition.edition_id, "lost")

    book = client.get(f"/api/v1/books/{work_id}").json()

    assert (book["title"], book["authors"]) == ("Gone Girl", ["Gillian Flynn"])
    assert book["description"] == "Gone Girl: a dark psychological thriller"
    assert [e["isbn13"] for e in book["editions"]] == ["9780307588371"]
    assert [c["status"] for c in book["copies"]] == ["available", "on_loan"]  # lost left out
    assert book["copies"][1]["due_date"] == "2026-10-10"
    assert book["availability"]["available_copies"] == 1
    assert client.get("/api/v1/books/999999999").status_code == 404
