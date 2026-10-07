import pytest
from sqlalchemy import Connection, insert

from shelfwise.catalog import schema
from shelfwise.query.cascade import CatalogLinker, fast_lookup
from shelfwise.query.rules import parse_rules

from .factories import add_author, add_edition, add_work

BOOKS = [
    ("Harry Potter and the Goblet of Fire", "J. K. Rowling"),
    ("Simon vs. the Homo Sapiens Agenda", "Becky Albertalli"),
    ("Fifty Shades of Grey", "E. L. James"),
    ("Oliver Twist", "Charles Dickens"),
    ("Gone Girl", "Gillian Flynn"),
]


@pytest.fixture
def linker(conn: Connection) -> CatalogLinker:
    for title, author in BOOKS:
        work_id = add_work(conn, title)
        add_edition(conn, work_id)
        conn.execute(
            insert(schema.work_author).values(work_id=work_id, author_id=add_author(conn, author))
        )
    return CatalogLinker(conn)


def test_titles_link_to_the_catalog_spelling(linker: CatalogLinker) -> None:
    link = linker.title("harry poter goblet of fire")

    assert link is not None
    assert link.name == "Harry Potter and the Goblet of Fire"
    assert link.work_id is not None


@pytest.mark.parametrize("name", ["sapiens", "harry potter 8", "the dinosaur book"])
def test_weak_title_matches_are_not_trusted(linker: CatalogLinker, name: str) -> None:
    assert linker.title(name) is None


def test_authors_link_by_surname(linker: CatalogLinker) -> None:
    link = linker.author("dickens")

    assert link is not None and link.name == "Charles Dickens"


def test_every_given_word_must_be_in_the_author_name(linker: CatalogLinker) -> None:
    assert linker.author("james clear") is None  # not E. L. James


@pytest.mark.parametrize(
    ("query", "title", "author"),
    [
        ("do you have harry potter goblet of fire", "Harry Potter and the Goblet of Fire", None),
        ("oliver twist", "Oliver Twist", None),
        ("anything by charles dickens", None, "Charles Dickens"),
    ],
)
def test_fast_lookup_on_the_catalog(
    linker: CatalogLinker, query: str, title: str | None, author: str | None
) -> None:
    parse = fast_lookup(parse_rules(query), linker)

    assert parse is not None and parse.lookup is not None
    assert (parse.lookup.title, parse.lookup.author) == (title, author)


@pytest.mark.parametrize(
    "query", ["something like gone girl", "a twisty book about a girl", "harry potter"]
)
def test_fast_lookup_leaves_the_rest_to_the_llm(linker: CatalogLinker, query: str) -> None:
    assert fast_lookup(parse_rules(query), linker) is None
