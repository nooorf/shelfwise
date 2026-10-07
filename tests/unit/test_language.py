from pathlib import Path

from shelfwise.ingest.language import (
    description_language,
    load_excluded,
    non_english_reason,
    non_latin_share,
)

ENGLISH = "A famous painter shoots her husband and then never speaks another word to anyone."
FRENCH = "Amyas Crale, un peintre celebre, a ete assassine, et sa femme, condamnee pour ce crime."
PORTUGUESE = "Junto com Roland estão dois companheiros que ele levou consigo para esse universo."


def test_description_language() -> None:
    assert description_language(ENGLISH) is None
    assert description_language(FRENCH) == "fr"
    assert description_language(PORTUGUESE) == "pt"
    assert description_language("Un roman.") is None  # too short to judge
    assert description_language(None) is None


def test_non_latin_titles() -> None:
    assert non_latin_share("Как изгубих наивността си") == 1.0
    assert non_latin_share("Les Misérables") == 0.0  # accented Latin is still Latin
    assert non_english_reason("Как изгубих наивността си", ENGLISH) == (
        "title in a non-Latin script"
    )


def test_english_editions_with_foreign_titles_stay() -> None:
    assert non_english_reason("Les Misérables", ENGLISH) is None
    assert non_english_reason("Five Little Pigs", FRENCH) == "description in 'fr'"


def test_excluded_editions(tmp_path: Path) -> None:
    path = tmp_path / "excluded.csv"
    path.write_text("isbn13,reason\n9780785934516,French edition of Angels & Demons\n")

    excluded = load_excluded(path)

    assert non_english_reason("Anges et Demons", ENGLISH, ["9780785934516"], excluded) == (
        "excluded edition: French edition of Angels & Demons"
    )
    assert load_excluded(tmp_path / "missing.csv") == {}


def test_the_committed_exclusion_list_is_valid() -> None:
    excluded = load_excluded()
    assert excluded and all(len(isbn) == 13 and isbn.isdigit() for isbn in excluded)
