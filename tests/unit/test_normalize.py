import pytest

from shelfwise.ingest.normalize import (
    normalize_author,
    normalize_isbn,
    normalize_text,
    split_title,
    title_norm,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9781250301697", "9781250301697"),
        ("978-1-250-30169-7", "9781250301697"),
        ("0306406152", "9780306406157"),  # ISBN-10 converted
        ("080442957X", "9780804429573"),  # X check digit
        ("080442957x", "9780804429573"),
        ("9781250301698", None),  # bad checksum
        ("0306406153", None),  # bad ISBN-10 checksum
        ("1234567890123", None),  # not a 978/979 prefix
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_isbn(raw: str | None, expected: str | None) -> None:
    assert normalize_isbn(raw) == expected


def test_normalize_text_collapses_whitespace_and_nfkc() -> None:
    assert normalize_text("  The\u00a0Silent \n Patient  ") == "The Silent Patient"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("The Silent Patient", "silent patient"),
        ("A Game of Thrones", "game of thrones"),
        (
            "Harry Potter and the Goblet of Fire (Harry Potter, #4)",
            "harry potter and the goblet of fire",
        ),
        ("Cien años de soledad", "cien anos de soledad"),
        ("Gone Girl!", "gone girl"),
        ("Theory of Everything", "theory of everything"),  # "the" only as a whole word
    ],
)
def test_title_norm(title: str, expected: str) -> None:
    assert title_norm(title) == expected


def test_split_title_on_colon() -> None:
    assert split_title("Sapiens: A Brief History of Humankind") == (
        "Sapiens",
        "A Brief History of Humankind",
    )
    assert split_title("Dune", "Deluxe Edition") == ("Dune", "Deluxe Edition")
    assert split_title("Dune") == ("Dune", None)


@pytest.mark.parametrize(
    ("raw", "display", "key"),
    [
        ("Christie, Agatha", "Agatha Christie", "agatha christie"),
        ("Agatha Christie", "Agatha Christie", "agatha christie"),
        ("Tolkien, J. R. R. (John Ronald Reuel), 1892-1973", "J. R. R. Tolkien", "jrr tolkien"),
        ("J.R.R. Tolkien", "J.R.R. Tolkien", "jrr tolkien"),
        ("García Márquez, Gabriel", "Gabriel García Márquez", "gabriel garcia marquez"),
        ("King, Martin Luther, Jr.", "Martin Luther King Jr.", "martin luther king jr"),
        ("Martin Luther King, Jr.", "Martin Luther King, Jr.", "martin luther king jr"),
        ("Michaelides, Alex, 1977-", "Alex Michaelides", "alex michaelides"),
        ("Bo A Smith", "Bo A Smith", "bo a smith"),
    ],
)
def test_normalize_author(raw: str, display: str, key: str) -> None:
    assert normalize_author(raw) == (display, key)
