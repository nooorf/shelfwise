from datetime import date, timedelta

import pytest

from shelfwise.catalog.availability import (
    DUE_SOON_DAYS,
    AvailabilityState,
    WorkAvailability,
    availability_state,
)

TODAY = date(2026, 10, 6)


@pytest.mark.parametrize(
    ("available", "reference", "next_due", "expected"),
    [
        (2, 0, None, AvailabilityState.AVAILABLE),
        (1, 1, TODAY, AvailabilityState.AVAILABLE),
        (0, 1, TODAY + timedelta(days=2), AvailabilityState.IN_LIBRARY_ONLY),
        (0, 0, TODAY, AvailabilityState.DUE_SOON),
        (0, 0, TODAY + timedelta(days=DUE_SOON_DAYS), AvailabilityState.DUE_SOON),
        (0, 0, TODAY + timedelta(days=DUE_SOON_DAYS + 1), AvailabilityState.BORROWED),
        (0, 0, TODAY - timedelta(days=1), AvailabilityState.BORROWED),  # overdue
        (0, 0, None, AvailabilityState.UNAVAILABLE),
    ],
)
def test_availability_state(
    available: int, reference: int, next_due: date | None, expected: AvailabilityState
) -> None:
    assert availability_state(available, reference, next_due, TODAY) == expected


def test_work_without_copies_is_unavailable() -> None:
    assert WorkAvailability.none(42).state(TODAY) == AvailabilityState.UNAVAILABLE
