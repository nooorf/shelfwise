"""Tiny insert helpers for integration tests."""

import itertools
from datetime import date

from sqlalchemy import Connection, insert

from shelfwise.catalog import schema
from shelfwise.ingest.normalize import normalize_author, title_norm

_barcodes = itertools.count(1)


def add_work(
    conn: Connection,
    title: str = "The Silent Patient",
    first_pub_year: int | None = None,
    genres: list[str] | None = None,
) -> int:
    return conn.execute(
        insert(schema.work)
        .values(
            title=title,
            title_norm=title_norm(title),
            first_pub_year=first_pub_year,
            genres=genres or [],
        )
        .returning(schema.work.c.work_id)
    ).scalar_one()


def add_edition(
    conn: Connection,
    work_id: int,
    pages: int | None = 320,
    isbn13: str | None = None,
    pub_year: int | None = None,
) -> int:
    return conn.execute(
        insert(schema.edition)
        .values(work_id=work_id, pages=pages, isbn13=isbn13, pub_year=pub_year)
        .returning(schema.edition.c.edition_id)
    ).scalar_one()


def add_copy(
    conn: Connection,
    edition_id: int,
    status: str = "available",
    due_date: date | None = None,
    branch: str = "Main",
) -> int:
    return conn.execute(
        insert(schema.copy)
        .values(
            edition_id=edition_id,
            barcode=f"B{next(_barcodes):08d}",
            branch=branch,
            status=status,
            due_date=due_date,
        )
        .returning(schema.copy.c.copy_id)
    ).scalar_one()


def add_author(conn: Connection, name: str) -> int:
    display, name_norm = normalize_author(name)
    return conn.execute(
        insert(schema.author)
        .values(display=display, name_norm=name_norm)
        .returning(schema.author.c.author_id)
    ).scalar_one()
