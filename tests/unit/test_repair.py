import pytest

from shelfwise.voice.repair import Fix, NameRepair

REPAIR = NameRepair(
    authors=[
        "Gillian Flynn",
        "Stephen King",
        "Neil Gaiman",
        "Agatha Christie",
        "Brandon Sanderson",
    ],
    titles=[
        "Gone Girl",
        "The Girls",
        "And Then There Were None",
        "The Way of Kings",
        "Python Machine Learning",
    ],
)


@pytest.mark.parametrize(
    ("heard", "expected", "fixed"),
    [
        ("something like gone girl by jillian flynn", "something like gone girl by Gillian Flynn",
         [Fix("jillian flynn", "Gillian Flynn")]),
        ("anything by steven king?", "anything by Stephen King?", [Fix("steven king", "Stephen King")]),
        ("is the way of kinks available", "is The Way of Kings available",
         [Fix("the way of kinks", "The Way of Kings")]),
        ("a book about the girl next door", "a book about the girl next door", []),  # 2-word title
        ("cozy mysteries like agatha christie", "cozy mysteries like agatha christie", []),  # right
        ("gothic horror under three hundred pages", "gothic horror under three hundred pages", []),
        ("best intro to machine learning", "best intro to machine learning", []),  # "to" ≠ "python"
        ("", "", []),
    ],
)  # fmt: skip
def test_near_miss_names_take_the_catalog_spelling(
    heard: str, expected: str, fixed: list[Fix]
) -> None:
    assert REPAIR.repair(heard) == (expected, fixed)
