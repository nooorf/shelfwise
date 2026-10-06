from datetime import date, timedelta

from sqlalchemy import Connection, text, update

from shelfwise.catalog import schema
from shelfwise.catalog.availability import (
    AvailabilityState,
    WorkAvailability,
    fetch_live_availability,
    refresh_availability_view,
)

from .factories import add_copy, add_edition, add_work

TODAY = date(2026, 10, 6)


def test_live_availability_aggregates_across_editions(conn: Connection) -> None:
    work_id = add_work(conn)
    hardcover = add_edition(conn, work_id, pages=352)
    paperback = add_edition(conn, work_id, pages=336)
    add_copy(conn, hardcover, "available", branch="Main")
    add_copy(conn, paperback, "available", branch="East")
    add_copy(conn, paperback, "on_loan", due_date=TODAY + timedelta(days=3))
    add_copy(conn, paperback, "on_loan", due_date=TODAY + timedelta(days=10))
    add_copy(conn, paperback, "reference_only")
    add_copy(conn, paperback, "lost")

    result = fetch_live_availability(conn, [work_id])[work_id]

    assert result == WorkAvailability(
        work_id=work_id,
        available_copies=2,
        reference_copies=1,
        total_copies=5,  # lost copies don't count
        next_due=TODAY + timedelta(days=3),
        branches_available=("East", "Main"),
    )
    assert result.state(TODAY) == AvailabilityState.AVAILABLE


def test_live_read_sees_changes_the_view_has_not(conn: Connection) -> None:
    work_id = add_work(conn)
    copy_id = add_copy(conn, add_edition(conn, work_id), "available")
    refresh_availability_view(conn)

    conn.execute(
        update(schema.copy)
        .where(schema.copy.c.copy_id == copy_id)
        .values(status="on_loan", due_date=TODAY + timedelta(days=2))
    )

    stale = conn.execute(
        text("SELECT available_copies FROM work_availability WHERE work_id = :w"), {"w": work_id}
    ).scalar()
    live = fetch_live_availability(conn, [work_id])[work_id]

    assert stale == 1
    assert live.available_copies == 0
    assert live.state(TODAY) == AvailabilityState.DUE_SOON


def test_view_agrees_with_live_query_after_refresh(conn: Connection) -> None:
    work_ids = []
    for i, statuses in enumerate(
        [("available",), ("on_loan", "reference_only"), ("lost", "repair"), ("on_loan",)]
    ):
        work_id = add_work(conn, title=f"Book {i}")
        edition_id = add_edition(conn, work_id)
        for status in statuses:
            due = TODAY + timedelta(days=5) if status == "on_loan" else None
            add_copy(conn, edition_id, status, due_date=due)
        work_ids.append(work_id)

    refresh_availability_view(conn)
    rows = conn.execute(
        text(
            "SELECT work_id, available_copies, reference_copies, total_copies, next_due, "
            "branches_available FROM work_availability WHERE work_id = ANY(:ids)"
        ),
        {"ids": work_ids},
    )
    from_view = {
        r.work_id: WorkAvailability(
            r.work_id,
            r.available_copies,
            r.reference_copies,
            r.total_copies,
            r.next_due,
            tuple(sorted(r.branches_available)),
        )
        for r in rows
    }

    assert from_view == fetch_live_availability(conn, work_ids)


def test_work_without_copies_is_reported_unavailable(conn: Connection) -> None:
    work_id = add_work(conn)

    result = fetch_live_availability(conn, [work_id])

    assert result == {work_id: WorkAvailability.none(work_id)}
