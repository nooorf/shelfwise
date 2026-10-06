import random
from datetime import UTC, date, datetime

from sqlalchemy import Connection, text

from shelfwise.catalog.availability import fetch_live_availability
from shelfwise.catalog.circulation import populate_library, tick

from .factories import add_edition, add_work

TODAY = date(2026, 10, 6)


def seed_catalog(conn: Connection, n: int = 12) -> list[int]:
    work_ids = []
    for i in range(n):
        work_id = add_work(conn, title=f"Book {i}")
        add_edition(conn, work_id)
        work_ids.append(work_id)
    return work_ids


def open_loans_match_on_loan_copies(conn: Connection) -> bool:
    on_loan = set(conn.execute(text("SELECT copy_id FROM copy WHERE status = 'on_loan'")).scalars())
    open_loans = list(
        conn.execute(text("SELECT copy_id FROM loan WHERE returned_at IS NULL")).scalars()
    )
    return len(open_loans) == len(set(open_loans)) and set(open_loans) == on_loan


def test_populate_writes_copies_loans_and_popularity(conn: Connection) -> None:
    work_ids = seed_catalog(conn)

    stats = populate_library(conn, today=TODAY, seed=7)

    assert stats.works == len(work_ids)
    assert stats.copies >= len(work_ids)
    assert open_loans_match_on_loan_copies(conn)
    max_popularity = conn.execute(text("SELECT max(popularity) FROM work")).scalar()
    assert max_popularity == 1.0
    availability = fetch_live_availability(conn, work_ids)
    assert sum(a.total_copies for a in availability.values()) <= stats.copies


def test_populate_replaces_previous_simulation(conn: Connection) -> None:
    seed_catalog(conn)
    first = populate_library(conn, today=TODAY, seed=7)

    second = populate_library(conn, today=TODAY, seed=7)

    copies = conn.execute(text("SELECT count(*) FROM copy")).scalar()
    assert copies == first.copies == second.copies


def test_tick_keeps_loans_and_copies_consistent(conn: Connection) -> None:
    seed_catalog(conn)
    populate_library(conn, today=TODAY, seed=7)
    rng = random.Random(1)

    for _ in range(10):
        tick(conn, rng, datetime(2026, 10, 6, 15, 0, tzinfo=UTC), events=4)

    assert open_loans_match_on_loan_copies(conn)
    view_total = conn.execute(text("SELECT sum(available_copies) FROM work_availability")).scalar()
    live_total = conn.execute(text("SELECT count(*) FROM copy WHERE status = 'available'")).scalar()
    assert view_total == live_total
