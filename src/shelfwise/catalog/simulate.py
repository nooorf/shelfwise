"""Simulated library layer: shelves, copies and a year of circulation (design doc §10).

We build the catalog ourselves, so there is no real circulation data. This module invents a
plausible library around the real book metadata: each work gets a hidden *demand* level, popular
works get more copies, and 365 days of borrowing produce today's copy statuses, due dates and
loan history. Everything is deterministic for a given seed and "today", so runs are repeatable.
The UI labels availability as simulated.
"""

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from shelfwise.ingest.genres import NONFICTION_GENRES
from shelfwise.ingest.normalize import normalize_author

LOAN_DAYS = 14
HISTORY_DAYS = 365
BRANCH = "Main"
N_PATRONS = 2_000
# Mean borrow attempts per day for a work of demand 1.0.
BASE_DAILY_RATE = 0.012

FLOORS = {
    "1": "Children & Teens",
    "2": "Fiction",
    "3": "Nonfiction",
}

_KIDS_COMPATIBLE = {"children's", "young adult", "fantasy", "adventure", "humor", "graphic novels"}
# Rough Dewey classes for nonfiction call numbers.
_DEWEY = {
    "philosophy": "100",
    "psychology": "150",
    "self-help": "158",
    "religion": "200",
    "politics": "320",
    "true crime": "364",
    "science": "500",
    "business": "650",
    "essays": "814",
    "travel": "910",
    "biography": "920",
    "memoir": "920",
    "history": "900",
}
_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


# --- Inputs and outputs -----------------------------------------------------------------------


@dataclass(frozen=True)
class WorkInput:
    work_id: int
    edition_ids: tuple[int, ...]
    genres: tuple[str, ...]
    first_author: str | None


@dataclass
class CopyPlan:
    copy_index: int  # position in the plan; loans refer to it
    edition_id: int
    work_id: int
    barcode: str
    floor: str
    call_number: str
    status: str = "available"
    due_date: date | None = None


@dataclass(frozen=True)
class LoanPlan:
    copy_index: int
    patron_hash: str
    checkout_on: date
    due_on: date
    returned_on: date | None  # None = still out today


@dataclass
class SimulationResult:
    copies: list[CopyPlan] = field(default_factory=list)
    loans: list[LoanPlan] = field(default_factory=list)
    loan_counts: dict[int, int] = field(default_factory=dict)  # work_id -> loans in window

    def popularity(self) -> dict[int, float]:
        """log(1 + loans), scaled to 0..1 across the catalog."""
        top = max((math.log1p(n) for n in self.loan_counts.values()), default=0.0)
        return {w: (math.log1p(n) / top if top else 0.0) for w, n in self.loan_counts.items()}


# --- Shelving ---------------------------------------------------------------------------------


def _surname_code(author: str | None) -> str:
    if not author:
        return "ANO"
    tokens = [t for t in normalize_author(author)[1].split() if t not in _NAME_SUFFIXES]
    surname = tokens[-1] if tokens else "ano"
    return surname[:3].upper()


def shelve(genres: tuple[str, ...], author: str | None) -> tuple[str, str]:
    """Return (floor, call number) the way a public library would shelve the work."""
    code = _surname_code(author)
    genre_set = set(genres)
    if genre_set and genre_set <= _KIDS_COMPATIBLE:
        if "young adult" in genre_set:
            return "1", f"YA FIC {code}"
        if "children's" in genre_set:
            return "1", f"J FIC {code}"
        if "graphic novels" in genre_set:
            return "1", f"GN {code}"
    nonfiction = [g for g in genres if g in NONFICTION_GENRES]
    if nonfiction and len(nonfiction) == len(genre_set):
        return "3", f"{_DEWEY.get(nonfiction[0], '000')} {code}"
    return "2", f"FIC {code}"


# --- Simulation -------------------------------------------------------------------------------


def _patron(rng: random.Random) -> str:
    patron_id = rng.randrange(N_PATRONS)
    return hashlib.sha256(f"patron-{patron_id}".encode()).hexdigest()[:16]


def _copies_for(demand: float) -> int:
    return 1 + min(3, int(demand))  # 1..4


def _return_offset(rng: random.Random) -> int | None:
    """Days relative to the due date the book comes back; None = not back yet (long overdue)."""
    roll = rng.random()
    if roll < 0.005:
        return None
    if roll < 0.105:
        return rng.randint(1, 20)  # late
    return -rng.randint(0, LOAN_DAYS - 1)  # early or on time


def simulate(works: list[WorkInput], today: date, seed: int = 7) -> SimulationResult:
    rng = random.Random(seed)
    result = SimulationResult()
    # Heavy-tailed demand: a few books are very popular, most are borrowed occasionally.
    demand = {w.work_id: rng.lognormvariate(0.0, 1.0) for w in works}

    copies_by_work: dict[int, list[int]] = {}
    for work in works:
        floor, call_number = shelve(work.genres, work.first_author)
        for n in range(_copies_for(demand[work.work_id])):
            edition_id = work.edition_ids[n % len(work.edition_ids)]
            plan = CopyPlan(
                copy_index=len(result.copies),
                edition_id=edition_id,
                work_id=work.work_id,
                barcode=f"SW{edition_id:07d}{n:02d}",
                floor=floor,
                call_number=call_number,
            )
            result.copies.append(plan)
            copies_by_work.setdefault(work.work_id, []).append(plan.copy_index)

    # Some copies never circulate.
    for plan in result.copies:
        roll = rng.random()
        if roll < 0.03:
            plan.status = "reference_only"
        elif roll < 0.04:
            plan.status = "repair"
        elif roll < 0.05:
            plan.status = "lost"

    busy_until: dict[int, date | None] = {}  # copy_index -> date it comes back (None = never)
    start = today - timedelta(days=HISTORY_DAYS)
    unmet_recently: set[int] = set()

    def is_free(copy_index: int, day: date) -> bool:
        if result.copies[copy_index].status != "available":
            return False
        if copy_index not in busy_until:
            return True
        back = busy_until[copy_index]
        return back is not None and back <= day

    for offset in range(HISTORY_DAYS + 1):
        day = start + timedelta(days=offset)
        for work in works:
            # At most one borrow attempt per work per day; rate stays well below 1.
            if rng.random() >= min(0.9, BASE_DAILY_RATE * demand[work.work_id]):
                continue
            free = [i for i in copies_by_work[work.work_id] if is_free(i, day)]
            if not free:
                if (today - day).days <= 7:
                    unmet_recently.add(work.work_id)
                continue
            copy_index = rng.choice(free)
            due = day + timedelta(days=LOAN_DAYS)
            back_offset = _return_offset(rng)
            back = (
                None
                if back_offset is None
                else max(due + timedelta(days=back_offset), day + timedelta(days=1))
            )
            returned = back if back is not None and back <= today else None
            busy_until[copy_index] = back
            result.loans.append(LoanPlan(copy_index, _patron(rng), day, due, returned_on=returned))
            result.loan_counts[work.work_id] = result.loan_counts.get(work.work_id, 0) + 1

    # Today's status: copies still out are on loan.
    for loan in result.loans:
        if loan.returned_on is None:
            plan = result.copies[loan.copy_index]
            plan.status, plan.due_date = "on_loan", loan.due_on
    # Books people queued for this week: one returned copy is waiting on the hold shelf.
    for work_id in sorted(unmet_recently):
        for i in copies_by_work[work_id]:
            if result.copies[i].status == "available":
                result.copies[i].status = "on_hold"
                break
    for work in works:
        result.loan_counts.setdefault(work.work_id, 0)
    return result


def as_timestamp(day: date) -> datetime:
    """Loans happen at noon UTC on their day."""
    return datetime.combine(day, time(12, 0), tzinfo=UTC)
