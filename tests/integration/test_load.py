from sqlalchemy import Connection, Table, func, select

from shelfwise.catalog import schema
from shelfwise.catalog.meta import get_catalog_version
from shelfwise.ingest.cluster import cluster_editions
from shelfwise.ingest.load import load_clusters
from shelfwise.ingest.records import EditionRecord

RECORDS = [
    EditionRecord(
        isbn13="9781250301697",
        title="The Silent Patient",
        authors=["Alex Michaelides"],
        pages=336,
        pub_year=2019,
        description="Alicia Berenson's life is seemingly perfect.",
        subjects=["Fiction, psychological", "Psychotherapy patients"],
        source_work_key="/works/OL19096402W",
    ),
    EditionRecord(
        isbn13="9781250301710",
        title="The Silent Patient",
        authors=["Michaelides, Alex"],
        pages=352,
        pub_year=2021,
        source_work_key="/works/OL19096402W",
    ),
    EditionRecord(isbn13="9780307588371", title="Gone Girl", authors=["Gillian Flynn"]),
]


def count(conn: Connection, table: Table) -> int:
    return conn.execute(select(func.count()).select_from(table)).scalar_one()


def test_load_creates_works_editions_and_authors(conn: Connection) -> None:
    clusters, _ = cluster_editions(RECORDS)
    version_before = get_catalog_version(conn)

    stats = load_clusters(conn, clusters, source="seed")

    assert (stats.works_created, stats.editions_created) == (2, 3)
    assert count(conn, schema.author) == 2  # "Michaelides, Alex" is the same author
    assert stats.catalog_version == version_before + 1

    work = conn.execute(
        select(schema.work).where(schema.work.c.title_norm == "silent patient")
    ).one()
    assert work.source == "seed"
    assert work.genres == ["psychological thriller"]
    assert "psychotherapy patients" in work.tags
    assert work.description_source == "openlibrary"
    assert work.low_info is False

    gone_girl = conn.execute(
        select(schema.work).where(schema.work.c.title_norm == "gone girl")
    ).one()
    assert gone_girl.low_info is True
    assert gone_girl.description_source == "none"


def test_reloading_the_same_isbns_is_idempotent(conn: Connection) -> None:
    clusters, _ = cluster_editions(RECORDS)
    load_clusters(conn, clusters, source="seed")

    stats = load_clusters(conn, clusters, source="seed")

    assert (stats.works_created, stats.works_reused, stats.editions_created) == (0, 2, 0)
    assert count(conn, schema.work) == 2
    assert count(conn, schema.edition) == 3
