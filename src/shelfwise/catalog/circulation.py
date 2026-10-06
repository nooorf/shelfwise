"""Write the simulated library into the database, and keep it moving during demos."""

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Connection, bindparam, delete, insert, text, update

from shelfwise.catalog import schema
from shelfwise.catalog.availability import refresh_availability_view
from shelfwise.catalog.simulate import BRANCH, LOAN_DAYS, WorkInput, as_timestamp, simulate


@dataclass(frozen=True)
class PopulateStats:
    works: int
    copies: int
    loans: int
    on_loan_now: int


_WORK_INPUTS_SQL = text(
    """
    SELECT w.work_id,
           w.genres,
           array_agg(e.edition_id ORDER BY e.edition_id) AS edition_ids,
           (SELECT a.display FROM work_author wa JOIN author a USING (author_id)
             WHERE wa.work_id = w.work_id ORDER BY wa.position LIMIT 1) AS first_author
    FROM work w
    JOIN edition e USING (work_id)
    GROUP BY w.work_id
    ORDER BY w.work_id
    """
)


def load_work_inputs(conn: Connection) -> list[WorkInput]:
    return [
        WorkInput(row.work_id, tuple(row.edition_ids), tuple(row.genres), row.first_author)
        for row in conn.execute(_WORK_INPUTS_SQL)
    ]


def populate_library(conn: Connection, today: date, seed: int = 7) -> PopulateStats:
    """Replace all copies and loans with a fresh simulation. Popularity comes from loan counts."""
    works = load_work_inputs(conn)
    result = simulate(works, today=today, seed=seed)

    conn.execute(delete(schema.copy))  # cascades to loans
    copy_ids: list[int] = []
    if result.copies:
        copy_ids = list(
            conn.execute(
                insert(schema.copy).returning(schema.copy.c.copy_id, sort_by_parameter_order=True),
                [
                    {
                        "edition_id": c.edition_id,
                        "barcode": c.barcode,
                        "branch": BRANCH,
                        "floor": c.floor,
                        "call_number": c.call_number,
                        "status": c.status,
                        "due_date": c.due_date,
                        "status_at": as_timestamp(today),
                    }
                    for c in result.copies
                ],
            ).scalars()
        )
    if result.loans:
        conn.execute(
            insert(schema.loan),
            [
                {
                    "copy_id": copy_ids[loan.copy_index],
                    "patron_hash": loan.patron_hash,
                    "checkout_at": as_timestamp(loan.checkout_on),
                    "due_at": loan.due_on,
                    "returned_at": as_timestamp(loan.returned_on) if loan.returned_on else None,
                }
                for loan in result.loans
            ],
        )
    popularity = result.popularity()
    if popularity:
        conn.execute(
            update(schema.work)
            .where(schema.work.c.work_id == bindparam("wid"))
            .values(popularity=bindparam("pop")),
            [{"wid": w, "pop": p} for w, p in popularity.items()],
        )
    refresh_availability_view(conn)
    return PopulateStats(
        works=len(works),
        copies=len(result.copies),
        loans=len(result.loans),
        on_loan_now=sum(c.status == "on_loan" for c in result.copies),
    )


def tick(conn: Connection, rng: random.Random, now: datetime, events: int = 3) -> list[str]:
    """Apply a few random returns and checkouts, then refresh the availability view.

    Returns land soonest-due first; checkouts favor popular works (weighted random order).
    """
    log: list[str] = []
    for _ in range(events):
        if rng.random() < 0.5:
            row = conn.execute(
                text(
                    "SELECT copy_id FROM copy WHERE status = 'on_loan' "
                    "ORDER BY due_date, random() LIMIT 1"
                )
            ).first()
            if row is None:
                continue
            conn.execute(
                text(
                    "UPDATE copy SET status = 'available', due_date = NULL, status_at = :now "
                    "WHERE copy_id = :c"
                ),
                {"now": now, "c": row.copy_id},
            )
            conn.execute(
                text(
                    "UPDATE loan SET returned_at = :now WHERE copy_id = :c AND returned_at IS NULL"
                ),
                {"now": now, "c": row.copy_id},
            )
            log.append(f"returned copy {row.copy_id}")
        else:
            row = conn.execute(
                text(
                    "SELECT c.copy_id FROM copy c JOIN edition e USING (edition_id) "
                    "JOIN work w USING (work_id) WHERE c.status = 'available' "
                    "ORDER BY -ln(random()) / (w.popularity + 0.05) LIMIT 1"
                )
            ).first()
            if row is None:
                continue
            due = now.date() + timedelta(days=LOAN_DAYS)
            conn.execute(
                text(
                    "UPDATE copy SET status = 'on_loan', due_date = :due, status_at = :now "
                    "WHERE copy_id = :c"
                ),
                {"due": due, "now": now, "c": row.copy_id},
            )
            conn.execute(
                insert(schema.loan).values(
                    copy_id=row.copy_id,
                    patron_hash=f"{rng.getrandbits(64):016x}",
                    checkout_at=now,
                    due_at=due,
                )
            )
            log.append(f"checked out copy {row.copy_id}")
    refresh_availability_view(conn)
    return log
