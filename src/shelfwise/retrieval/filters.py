"""Hard constraints -> the set of works allowed to appear (design doc §9, §13.2).

Rules that keep this honest:

- Only *hard* constraints filter; soft ones are ranking signals.
- Edition-level conditions are checked together: "under 300 pages, available now" needs one
  edition that is short *and* has an available copy, not a short edition plus some other copy.
- Unknown values fail a hard condition (a work with no page count is not "under 300 pages").
- Exclusions are NULL-safe: excluding `supernatural = 'yes'` keeps works marked 'no', 'unclear'
  or not yet tagged; uncertain items are penalized by the ranker, not hidden.
- Values are always bound parameters, and a constraint this module doesn't understand raises
  instead of being silently ignored.
"""

import operator
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import (
    ColumnElement,
    Connection,
    Select,
    Text,
    and_,
    exists,
    func,
    literal,
    not_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY

from shelfwise.catalog import schema
from shelfwise.ingest.normalize import title_norm
from shelfwise.query.constraints import Constraint

_COMPARE: dict[str, Callable[[Any, Any], ColumnElement[bool]]] = {
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
    "eq": operator.eq,
}
FACET_COLUMNS = (
    "darkness", "romance", "violence", "pace", "supernatural", "audience", "fiction",
    "historical_setting", "reading_level",
)  # fmt: skip
_EDITION_FIELDS = {"pages", "isbn", "language"}


class UnsupportedConstraint(ValueError):
    pass


def _number(c: Constraint) -> int:
    if isinstance(c.value, bool) or not isinstance(c.value, int | float):
        raise UnsupportedConstraint(f"{c.field} needs a number, got {c.value!r}")
    return int(c.value)


def _compare(column: ColumnElement[Any], c: Constraint, value: Any) -> ColumnElement[bool]:
    if c.op not in _COMPARE:
        raise UnsupportedConstraint(f"{c.field} does not support op {c.op!r} as a hard filter")
    return _COMPARE[c.op](column, value)


def _values(c: Constraint) -> list[Any]:
    values = c.value if isinstance(c.value, list | tuple | set) else [c.value]
    return list(values)


def _membership(column: ColumnElement[Any], c: Constraint) -> ColumnElement[bool]:
    if c.op == "eq":
        return column == c.value
    if c.op in ("in", "not_in"):
        condition = column.in_(_values(c))
        return not_(condition) if c.op == "not_in" else condition
    raise UnsupportedConstraint(f"{c.field} does not support op {c.op!r}")


def _original_year() -> ColumnElement[Any]:
    """The work's first publication year, else its earliest edition's year."""
    earliest = (
        select(func.min(schema.edition.c.pub_year))
        .where(schema.edition.c.work_id == schema.work.c.work_id)
        .scalar_subquery()
    )
    return func.coalesce(schema.work.c.first_pub_year, earliest)


def _work_condition(c: Constraint) -> ColumnElement[bool]:
    work = schema.work
    if c.field == "year":
        return _compare(_original_year(), c, _number(c))
    if c.field == "genre":
        overlap = work.c.genres.overlap(literal(_values(c), ARRAY(Text)))
        if c.op == "in":
            return overlap
        if c.op == "not_in":
            return not_(overlap)
        raise UnsupportedConstraint(f"genre does not support op {c.op!r}")
    if c.field == "work_id":
        return _membership(work.c.work_id, c)
    if c.field == "title":  # "other than 1984": every work with that title, any edition
        if c.op != "eq":
            raise UnsupportedConstraint(f"title does not support op {c.op!r}")
        return work.c.title_norm == title_norm(str(c.value))
    if c.field == "author_id":
        wa = schema.work_author
        return exists().where(wa.c.work_id == work.c.work_id, _membership(wa.c.author_id, c))
    if c.field.startswith("facet."):
        name = c.field.removeprefix("facet.")
        if name not in FACET_COLUMNS:
            raise UnsupportedConstraint(f"unknown facet {name!r}")
        column = schema.work_facets.c[name]
        value_check = (
            _compare(column, c, c.value)
            if c.op in _COMPARE and c.op != "eq"
            else _membership(column, c)
        )
        wf = schema.work_facets
        return exists().where(wf.c.work_id == work.c.work_id, value_check)
    raise UnsupportedConstraint(f"no hard filter for field {c.field!r}")


def _edition_condition(c: Constraint, edition: Any) -> ColumnElement[bool]:
    if c.field == "pages":
        return _compare(edition.c.pages, c, _number(c))
    if c.field == "isbn":
        return _membership(edition.c.isbn13, c.model_copy(update={"op": "in"}))
    if c.field == "language":
        return _membership(edition.c.language, c)
    raise UnsupportedConstraint(f"no edition filter for field {c.field!r}")


def filter_query(constraints: Iterable[Constraint]) -> Select[int]:
    """SELECT work_id for works satisfying every hard constraint."""
    work_conditions: list[ColumnElement[bool]] = []
    edition = schema.edition.alias("e")
    edition_conditions: list[ColumnElement[bool]] = []
    need_available = False

    for c in constraints:
        if c.strength != "hard":
            continue
        if c.field == "available_now":
            if c.value is not True or c.polarity == "exclude":
                raise UnsupportedConstraint(
                    "only 'available now' is a supported availability filter"
                )
            need_available = True
            continue
        if c.field in _EDITION_FIELDS:
            if c.polarity == "exclude":
                raise UnsupportedConstraint(f"cannot exclude on edition field {c.field!r}")
            edition_conditions.append(_edition_condition(c, edition))
            continue
        condition = _work_condition(c)
        if c.polarity == "exclude":
            # NULL-safe: unknown values are kept, not excluded.
            condition = not_(func.coalesce(condition, False))
        work_conditions.append(condition)

    if edition_conditions or need_available:
        inner = [edition.c.work_id == schema.work.c.work_id, *edition_conditions]
        if need_available:
            inner.append(
                exists().where(
                    schema.copy.c.edition_id == edition.c.edition_id,
                    schema.copy.c.status == "available",
                )
            )
        work_conditions.append(exists().where(and_(*inner)))

    return select(schema.work.c.work_id).where(and_(true(), *work_conditions))


def filterable(c: Constraint) -> bool:
    """Whether `c` works as a hard filter (a chip can switch to "must"). Builds the query, runs
    nothing."""
    try:
        filter_query([c.model_copy(update={"strength": "hard"})])
    except UnsupportedConstraint:
        return False
    return True


def allowed_work_ids(conn: Connection, constraints: Iterable[Constraint]) -> set[int]:
    return set(conn.execute(filter_query(constraints)).scalars())


def allowed_mask(
    conn: Connection, constraints: Iterable[Constraint], work_ids: np.ndarray
) -> np.ndarray:
    """Boolean mask aligned with `work_ids` (e.g. a search index's row order)."""
    return np.isin(work_ids, list(allowed_work_ids(conn, constraints)))


@dataclass(frozen=True)
class Relaxation:
    dropped: tuple[Constraint, ...]
    count: int
    # Dropping "available now": when the first of those books is due back (design doc §12.3).
    earliest_due: date | None = None

    @property
    def label(self) -> str:
        return (
            self.dropped[0].span
            or f"{self.dropped[0].field} {self.dropped[0].op} {self.dropped[0].value}"
        )


def relaxations(conn: Connection, constraints: list[Constraint]) -> list[Relaxation]:
    """For each hard constraint (constraints sharing a span drop together, e.g. "2010s" = two
    bounds), how many works match if only that one is dropped. Most results first."""
    hard = [c for c in constraints if c.strength == "hard"]
    groups: dict[tuple[str, str], list[Constraint]] = {}
    for i, c in enumerate(hard):
        groups.setdefault((c.field, c.span or f"#{i}"), []).append(c)
    results = []
    for group in groups.values():
        rest = [c for c in hard if all(c is not g for g in group)]
        count = conn.execute(
            select(func.count()).select_from(filter_query(rest).subquery())
        ).scalar_one()
        due = earliest_due(conn, rest) if any(c.field == "available_now" for c in group) else None
        results.append(Relaxation(tuple(group), int(count), due))
    return sorted(results, key=lambda r: -r.count)


def earliest_due(conn: Connection, constraints: list[Constraint]) -> date | None:
    """The soonest due date among borrowed copies of the works matching `constraints`."""
    allowed = filter_query(constraints).subquery()
    return conn.execute(
        select(func.min(schema.copy.c.due_date))
        .select_from(schema.copy.join(schema.edition))
        .where(
            schema.edition.c.work_id.in_(select(allowed.c.work_id)),
            schema.copy.c.status == "on_loan",
        )
    ).scalar_one()
