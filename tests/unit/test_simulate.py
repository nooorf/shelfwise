from collections import defaultdict
from datetime import date, timedelta
from itertools import pairwise

import pytest

from shelfwise.catalog.simulate import (
    HISTORY_DAYS,
    LOAN_DAYS,
    SimulationResult,
    WorkInput,
    shelve,
    simulate,
)

TODAY = date(2026, 10, 6)
WORKS = [
    WorkInput(i, (100 + i,), genres, author)
    for i, (genres, author) in enumerate(
        [
            (("thriller", "psychological thriller"), "Alex Michaelides"),
            (("fantasy", "young adult"), "Leigh Bardugo"),
            (("history",), "Yuval Noah Harari"),
            ((), None),
        ]
        * 10
    )
]


@pytest.fixture(scope="module")
def result() -> SimulationResult:
    return simulate(WORKS, today=TODAY, seed=7)


@pytest.mark.parametrize(
    ("genres", "author", "expected"),
    [
        (("thriller",), "Alex Michaelides", ("2", "FIC MIC")),
        (("fantasy", "young adult"), "Leigh Bardugo", ("1", "YA FIC BAR")),
        (("children's", "humor"), "Jeff Kinney", ("1", "J FIC KIN")),
        (("graphic novels",), "Alan Moore", ("1", "GN MOO")),
        (("history",), "Yuval Noah Harari", ("3", "900 HAR")),
        (("psychology", "self-help"), "Daniel Kahneman", ("3", "150 KAH")),
        # Noisy "children's" tag on an adult classic must not send it to the kids' floor.
        (("historical fiction", "children's", "classics"), "Charles Dickens", ("2", "FIC DIC")),
        (("memoir",), "Martin Luther King, Jr.", ("3", "920 KIN")),
        ((), None, ("2", "FIC ANO")),
    ],
)
def test_shelve(genres: tuple[str, ...], author: str | None, expected: tuple[str, str]) -> None:
    assert shelve(genres, author) == expected


def test_simulation_is_deterministic(result: SimulationResult) -> None:
    again = simulate(WORKS, today=TODAY, seed=7)

    assert again.copies == result.copies
    assert again.loans == result.loans


def test_every_work_gets_one_to_four_copies(result: SimulationResult) -> None:
    per_work = defaultdict(int)
    for plan in result.copies:
        per_work[plan.work_id] += 1

    assert set(per_work) == {w.work_id for w in WORKS}
    assert all(1 <= n <= 4 for n in per_work.values())
    assert len({c.barcode for c in result.copies}) == len(result.copies)


def test_a_copy_is_never_lent_twice_at_once(result: SimulationResult) -> None:
    by_copy = defaultdict(list)
    for loan in result.loans:
        by_copy[loan.copy_index].append(loan)

    for loans in by_copy.values():
        loans.sort(key=lambda loan: loan.checkout_on)
        for earlier, later in pairwise(loans):
            assert earlier.returned_on is not None
            assert earlier.returned_on <= later.checkout_on


def test_loans_stay_inside_the_window(result: SimulationResult) -> None:
    start = TODAY - timedelta(days=HISTORY_DAYS)

    assert result.loans
    for loan in result.loans:
        assert start <= loan.checkout_on <= TODAY
        assert loan.due_on == loan.checkout_on + timedelta(days=LOAN_DAYS)
        assert loan.returned_on is None or loan.checkout_on < loan.returned_on <= TODAY


def test_statuses_match_open_loans(result: SimulationResult) -> None:
    open_loans = {loan.copy_index: loan for loan in result.loans if loan.returned_on is None}

    for plan in result.copies:
        if plan.copy_index in open_loans:
            assert plan.status == "on_loan"
            assert plan.due_date == open_loans[plan.copy_index].due_on
        else:
            assert plan.status != "on_loan" and plan.due_date is None


def test_non_circulating_copies_have_no_loans(result: SimulationResult) -> None:
    loaned = {loan.copy_index for loan in result.loans}
    for plan in result.copies:
        if plan.status in {"reference_only", "repair", "lost"}:
            assert plan.copy_index not in loaned


def test_popularity_is_scaled_to_unit_interval(result: SimulationResult) -> None:
    popularity = result.popularity()

    assert set(popularity) == {w.work_id for w in WORKS}
    assert all(0.0 <= p <= 1.0 for p in popularity.values())
    assert max(popularity.values()) == pytest.approx(1.0)
