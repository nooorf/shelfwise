from pathlib import Path
from typing import Any

import pytest

from shelfwise.ingest.openlibrary import OpenLibraryClient, clean_description, parse_year

# Trimmed real responses for ISBN 9781250301697.
RESPONSES: dict[str, dict[str, Any]] = {
    "/isbn/9781250301697.json": {
        "title": "The Silent Patient",
        "publishers": ["Celadon Books"],
        "publish_date": "Feb 05, 2019",
        "number_of_pages": 336,
        "physical_format": "Hardcover",
        "authors": [{"key": "/authors/OL7471384A"}],
        "works": [{"key": "/works/OL19096402W"}],
        "languages": [{"key": "/languages/eng"}],
    },
    "/works/OL19096402W.json": {
        "title": "The Silent Patient",
        "description": "Alicia Berenson's life is seemingly perfect.",
        "subjects": ["Fiction, psychological", "Fiction, thrillers"],
        "covers": [9407338],
    },
    "/authors/OL7471384A.json": {"name": "Alex Michaelides"},
}


class FakeFetch:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, path: str) -> dict[str, Any] | None:
        self.calls.append(path)
        return self.responses.get(path)


@pytest.fixture
def fetch() -> FakeFetch:
    return FakeFetch(RESPONSES)


def make_client(tmp_path: Path, fetch: FakeFetch) -> OpenLibraryClient:
    return OpenLibraryClient(tmp_path, fetch=fetch, min_interval=0)


def test_lookup_builds_edition_record(tmp_path: Path, fetch: FakeFetch) -> None:
    record = make_client(tmp_path, fetch).lookup_isbn("9781250301697")

    assert record is not None
    assert record.title == "The Silent Patient"
    assert record.authors == ["Alex Michaelides"]
    assert record.publisher == "Celadon Books"
    assert record.pub_year == 2019
    assert record.pages == 336
    assert record.language == "en"
    assert record.description == "Alicia Berenson's life is seemingly perfect."
    assert record.subjects == ["Fiction, psychological", "Fiction, thrillers"]
    assert record.source_work_key == "/works/OL19096402W"
    assert record.cover_id == 9407338


def test_unknown_isbn_returns_none(tmp_path: Path, fetch: FakeFetch) -> None:
    assert make_client(tmp_path, fetch).lookup_isbn("9780000000002") is None


def test_responses_and_misses_are_cached_on_disk(tmp_path: Path, fetch: FakeFetch) -> None:
    make_client(tmp_path, fetch).lookup_isbn("9781250301697")
    make_client(tmp_path, fetch).lookup_isbn("9780000000002")
    calls_after_first_run = len(fetch.calls)

    fresh = make_client(tmp_path, fetch)
    fresh.lookup_isbn("9781250301697")
    fresh.lookup_isbn("9780000000002")

    assert len(fetch.calls) == calls_after_first_run


def test_falls_back_to_work_authors(tmp_path: Path) -> None:
    responses = {
        **RESPONSES,
        "/isbn/9781250301697.json": {**RESPONSES["/isbn/9781250301697.json"], "authors": []},
        "/works/OL19096402W.json": {
            **RESPONSES["/works/OL19096402W.json"],
            "authors": [{"author": {"key": "/authors/OL7471384A"}}],
        },
    }
    record = make_client(tmp_path, FakeFetch(responses)).lookup_isbn("9781250301697")

    assert record is not None and record.authors == ["Alex Michaelides"]


def test_bad_page_counts_are_dropped(tmp_path: Path) -> None:
    responses = {
        **RESPONSES,
        "/isbn/9781250301697.json": {**RESPONSES["/isbn/9781250301697.json"], "number_of_pages": 0},
    }
    record = make_client(tmp_path, FakeFetch(responses)).lookup_isbn("9781250301697")

    assert record is not None and record.pages is None


def test_clean_description_handles_both_shapes() -> None:
    assert clean_description({"type": "/type/text", "value": "A story."}) == "A story."
    assert (
        clean_description("A story. ([source][1])\n----------\n[1]: http://example.com")
        == "A story."
    )
    assert clean_description(None) is None


def test_parse_year() -> None:
    assert parse_year("Feb 05, 2019") == 2019
    assert parse_year("c1998") == 1998
    assert parse_year("unknown") is None
