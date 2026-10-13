"""Copy-level availability.

Availability is computed from `copy.status`, never stored on the work. The `work_availability`
materialized view serves the ranker (refreshed after each sync); `fetch_live_availability` re-reads
the copy table for the handful of books about to be shown, so responses are never stale.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import Connection, text

DUE_SOON_DAYS = 7


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    IN_LIBRARY_ONLY = "in_library_only"  # reference copy: read on site, cannot borrow
    DUE_SOON = "due_soon"
    BORROWED = "borrowed"
    UNAVAILABLE = "unavailable"  # no borrowable or reference copies (lost, repair, none)


def availability_state(
    available_copies: int,
    reference_copies: int,
    next_due: date | None,
    today: date,
) -> AvailabilityState:
    if available_copies > 0:
        return AvailabilityState.AVAILABLE
    if reference_copies > 0:
        return AvailabilityState.IN_LIBRARY_ONLY
    if next_due is None:
        return AvailabilityState.UNAVAILABLE
    # Overdue loans may come back any day or never; don't promise "soon".
    if today <= next_due and (next_due - today).days <= DUE_SOON_DAYS:
        return AvailabilityState.DUE_SOON
    return AvailabilityState.BORROWED


@dataclass(frozen=True)
class WorkAvailability:
    work_id: int
    available_copies: int
    reference_copies: int
    total_copies: int
    next_due: date | None
    branches_available: tuple[str, ...]

    def state(self, today: date) -> AvailabilityState:
        return availability_state(
            self.available_copies, self.reference_copies, self.next_due, today
        )

    @classmethod
    def none(cls, work_id: int) -> "WorkAvailability":
        """A work with no copies at all."""
        return cls(work_id, 0, 0, 0, None, ())


# Keep in sync with the work_availability view in migrations/versions/0001_catalog_schema.py;
# tests/integration/test_availability.py checks they agree.
_LIVE_AVAILABILITY_SQL = text(
    """
    SELECT e.work_id,
           count(*) FILTER (WHERE c.status = 'available')      AS available_copies,
           count(*) FILTER (WHERE c.status = 'reference_only') AS reference_copies,
           count(*) FILTER (WHERE c.status <> 'lost')          AS total_copies,
           min(c.due_date) FILTER (WHERE c.status = 'on_loan') AS next_due,
           coalesce(
               array_agg(DISTINCT c.branch) FILTER (WHERE c.status = 'available'), '{}'
           )                                                   AS branches_available
    FROM edition e
    JOIN copy c USING (edition_id)
    WHERE e.work_id = ANY(:work_ids)
    GROUP BY e.work_id
    """
)


def fetch_live_availability(
    conn: Connection, work_ids: Iterable[int]
) -> dict[int, WorkAvailability]:
    """Availability straight from the copy table. Works without copies map to `none()`."""
    ids = list(dict.fromkeys(work_ids))
    found = {
        row.work_id: WorkAvailability(
            work_id=row.work_id,
            available_copies=row.available_copies,
            reference_copies=row.reference_copies,
            total_copies=row.total_copies,
            next_due=row.next_due,
            branches_available=tuple(sorted(row.branches_available)),
        )
        for row in conn.execute(_LIVE_AVAILABILITY_SQL, {"work_ids": ids})
    }
    return {work_id: found.get(work_id, WorkAvailability.none(work_id)) for work_id in ids}


def refresh_availability_view(conn: Connection) -> None:
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY work_availability"))
