from typing import Any

import pytest

from shelfwise.ingest.genres import map_subjects
from shelfwise.ingest.goodreads import (
    clean_description,
    quotas,
    rejection,
    shelves_to_subjects,
    strip_series,
    to_record,
)

DESCRIPTION = (
    "Alicia Berenson's life is seemingly perfect. A famous painter married to an in-demand "
    "fashion photographer, she lives in a grand house in London. One evening she shoots him."
)


def book(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "work_id": "53064476",
        "isbn": "1250301696",
        "isbn13": "9781250301697",
        "title": "The Silent Patient (Standalone)",
        "title_without_series": "The Silent Patient",
        "language_code": "eng",
        "num_pages": "336",
        "format": "Hardcover",
        "publisher": "Celadon Books",
        "publication_year": "2019",
        "description": DESCRIPTION,
        "authors": [{"author_id": "1", "role": ""}, {"author_id": "2", "role": "Narrator"}],
        "popular_shelves": [
            {"count": "5000", "name": "to-read"},
            {"count": "900", "name": "thriller"},
            {"count": "700", "name": "psychological-thriller"},
            {"count": "400", "name": "favorites"},
            {"count": "300", "name": "fiction"},
            {"count": "20", "name": "read-in-2019"},
            {"count": "5", "name": "london"},
        ],
    }
    return raw | overrides


def test_a_complete_english_book_is_usable() -> None:
    assert rejection(book()) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"language_code": "spa"}, "not English"),
        ({"language_code": ""}, "not English"),
        ({"isbn13": "", "isbn": ""}, "no valid ISBN"),
        ({"isbn13": "9781250301690", "isbn": ""}, "no valid ISBN"),  # bad checksum
        ({"num_pages": ""}, "no page count"),
        ({"format": "Audio CD"}, "audiobook"),
        ({"description": "A thriller."}, "no description"),
        ({"authors": [{"author_id": "2", "role": "Illustrator"}]}, "no author"),
    ],
)
def test_unusable_books_say_why(overrides: dict[str, Any], reason: str) -> None:
    assert rejection(book(**overrides)) == reason


def test_isbn10_is_accepted_when_isbn13_is_missing() -> None:
    assert rejection(book(isbn13="")) is None
    record = to_record(book(isbn13=""), {"1": "Alex Michaelides"}, 2019)
    assert record is not None and record.isbn13 == "9781250301697"


def test_record_uses_title_without_series_and_primary_authors_only() -> None:
    record = to_record(book(), {"1": "Alex Michaelides", "2": "Jack Hawkins"}, 2019)

    assert record is not None
    assert record.title == "The Silent Patient"
    assert record.authors == ["Alex Michaelides"]  # the narrator is not an author
    assert (record.pages, record.pub_year, record.first_pub_year) == (336, 2019, 2019)
    assert record.source_work_key == "goodreads:53064476"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("The Hunger Games (The Hunger Games, #1)", "The Hunger Games"),
        ("Plague (Gone #4)", "Plague"),
        ("Clockwork Prince (The Infernal Devices, #2.5)", "Clockwork Prince"),
        ("Gone Girl", "Gone Girl"),
        ("Persepolis (The Complete)", "Persepolis (The Complete)"),  # not a series number
    ],
)
def test_series_suffix_is_stripped(title: str, expected: str) -> None:
    assert strip_series(title) == expected


def test_shelves_named_after_the_author_are_dropped() -> None:
    raw = book(popular_shelves=[{"count": "90", "name": "thriller"},
                                {"count": "80", "name": "alex-michaelides"}])  # fmt: skip

    record = to_record(raw, {"1": "Alex Michaelides"}, 2019)

    assert record is not None and record.subjects == ["thriller"]


def test_unknown_author_gives_no_record() -> None:
    assert to_record(book(), {}, None) is None


def test_reader_shelves_become_subjects_that_map_to_genres() -> None:
    subjects = shelves_to_subjects(book()["popular_shelves"])

    assert subjects == ["thriller", "psychological thriller", "fiction"]  # meta and rare dropped
    genres, _ = map_subjects(subjects)
    assert genres[:2] == ["psychological thriller", "thriller"]


def test_shelf_shorthand_is_expanded() -> None:
    shelves = [{"count": "50", "name": "ya"}, {"count": "40", "name": "middle-grade"},
               {"count": "30", "name": "sci-fi"}]  # fmt: skip

    subjects = shelves_to_subjects(shelves)

    assert subjects == ["young adult", "children's", "sci fi"]
    assert set(map_subjects(subjects)[0]) == {"young adult", "children's", "science fiction"}


def test_description_html_is_cleaned() -> None:
    assert clean_description("Murder<br /><br />in   Paris &amp; London") == (
        "Murder in Paris & London"
    )
    assert clean_description("  ") is None


def test_quotas_sum_to_the_total() -> None:
    counts = quotas(5003)

    assert sum(counts.values()) == 5003
    assert counts["mystery_thriller_crime"] >= counts["poetry"]
