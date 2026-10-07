import pytest
from sqlalchemy import Connection, insert

from shelfwise.catalog import schema
from shelfwise.retrieval.lexical import build_lexical_index
from shelfwise.retrieval.lookup import find_authors, find_by_isbn, find_titles, isbns_in

from .factories import add_author, add_edition, add_work

BOOKS = [
    ("The Silent Patient", "Alex Michaelides", "9781250301697"),
    ("Agatha Christie's Murder on the Orient Express", "Agatha Christie", None),
    ("Harry Potter and the Goblet of Fire", "J. K. Rowling", None),
    ("Moby Dick", "Herman Melville", None),
    ("Oliver Twist", "Charles Dickens", None),
    ("It", "Stephen King", None),
    ("Dune", "Frank Herbert", None),
    ("Principia", "Isaac Newton", None),
]


@pytest.fixture
def catalog(conn: Connection) -> dict[str, int]:
    ids = {}
    for title, author, isbn in BOOKS:
        work_id = add_work(conn, title)
        add_edition(conn, work_id, isbn13=isbn)
        conn.execute(
            insert(schema.work_author).values(work_id=work_id, author_id=add_author(conn, author))
        )
        ids[title] = work_id
    return ids


def titles_found(conn: Connection, query: str) -> list[str]:
    return [m.title for m in find_titles(conn, query)]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("do you have the silent patient", "The Silent Patient"),
        ("the silent pateint", "The Silent Patient"),
        ("murder on the orient expres", "Agatha Christie's Murder on the Orient Express"),
        ("harry potter goblet of fire", "Harry Potter and the Goblet of Fire"),
        ("do you have dune", "Dune"),
    ],
)
def test_finds_titles_despite_typos_and_extra_words(
    conn: Connection, catalog: dict[str, int], query: str, expected: str
) -> None:
    assert titles_found(conn, query)[:1] == [expected]


@pytest.mark.parametrize(
    "query",
    [
        "Works by Dickens published before 1900",  # not Moby Dick
        "something dark and psychological with a twist",  # not Oliver Twist
        "harry poter half blood prince",  # a book we don't have; not Principia
        "is it checked out",  # "it" is too short to trust
    ],
)
def test_partial_word_hits_are_suppressed(
    conn: Connection, catalog: dict[str, int], query: str
) -> None:
    assert titles_found(conn, query) == []


def test_finds_authors_by_full_name_and_surname(conn: Connection, catalog: dict[str, int]) -> None:
    assert [a.name for a in find_authors(conn, "anything by stephen king")][:1] == ["Stephen King"]
    dickens = find_authors(conn, "Works by Dickens published before 1900")
    assert [a.name for a in dickens] == ["Charles Dickens"]
    assert dickens[0].work_ids == (catalog["Oliver Twist"],)


def test_finds_works_by_isbn_inside_text(conn: Connection, catalog: dict[str, int]) -> None:
    assert isbns_in("isbn 978-1-250-30169-7 please") == ["9781250301697"]
    assert find_by_isbn(conn, "978-1-250-30169-7") == [catalog["The Silent Patient"]]
    assert find_by_isbn(conn, "9780000000000") == []


def test_index_built_from_database_includes_authors(
    conn: Connection, catalog: dict[str, int]
) -> None:
    index = build_lexical_index(conn)

    assert [h.work_id for h in index.search("herbert")] == [catalog["Dune"]]


def test_a_longer_title_that_explains_the_whole_query_beats_short_fragments(
    conn: Connection, catalog: dict[str, int]
) -> None:
    for title in ("Half-Blood", "The Prince"):
        add_work(conn, title)
    add_work(conn, "Harry Potter and the Half-Blood Prince")

    assert titles_found(conn, "harry poter half blood prince")[0] == (
        "Harry Potter and the Half-Blood Prince"
    )


def test_a_title_matching_one_word_of_a_longer_request_is_not_a_lookup(
    conn: Connection, catalog: dict[str, int]
) -> None:
    add_work(conn, "Home")
    add_work(conn, "Night")

    assert titles_found(conn, "thrillers i can take home today") == []
    assert titles_found(conn, "what horror books are available right now") == []


def test_a_surname_that_is_also_a_common_word_needs_the_first_name(
    conn: Connection, catalog: dict[str, int]
) -> None:
    young = add_work(conn, "Before Jamaica Lane")
    conn.execute(
        insert(schema.work_author).values(
            work_id=young, author_id=add_author(conn, "Samantha Young")
        )
    )
    for title in ("Letters to a Young Poet", "The Young Elites"):  # "young" is an ordinary word
        add_work(conn, title)

    assert [a.name for a in find_authors(conn, "available young adult fantasy")] == []
    assert [a.name for a in find_authors(conn, "books by samantha young")] == ["Samantha Young"]
    assert [a.name for a in find_authors(conn, "works by dickens")] == ["Charles Dickens"]
