"""Write work clusters into the catalog. Idempotent: re-importing the same ISBNs adds nothing.

A cluster joins an existing work if it shares an ISBN with it or, across sources, has the same
normalized title and first author (the clustering rule, applied to what's already loaded).
"""

from dataclasses import dataclass

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from shelfwise.catalog import schema
from shelfwise.catalog.meta import bump_catalog_version
from shelfwise.ingest.cluster import WorkCluster
from shelfwise.ingest.genres import map_subjects
from shelfwise.ingest.normalize import normalize_author


@dataclass
class LoadStats:
    works_created: int = 0
    works_reused: int = 0
    editions_created: int = 0
    catalog_version: int = 0


def _author_id(conn: Connection, raw_name: str) -> int:
    display, name_norm = normalize_author(raw_name)
    conn.execute(
        insert(schema.author)
        .values(display=display, name_norm=name_norm)
        .on_conflict_do_nothing(index_elements=["name_norm"])
    )
    return conn.execute(
        select(schema.author.c.author_id).where(schema.author.c.name_norm == name_norm)
    ).scalar_one()


def _existing_work_id(conn: Connection, cluster: WorkCluster) -> int | None:
    by_isbn = conn.execute(
        select(schema.edition.c.work_id).where(schema.edition.c.isbn13.in_(cluster.isbns)).limit(1)
    ).scalar()
    if by_isbn is not None or not cluster.authors:
        return by_isbn
    return conn.execute(
        select(schema.work.c.work_id)
        .join(schema.work_author, schema.work_author.c.work_id == schema.work.c.work_id)
        .join(schema.author, schema.author.c.author_id == schema.work_author.c.author_id)
        .where(
            schema.work.c.title_norm == cluster.title_norm,
            schema.work_author.c.position == 1,
            schema.author.c.name_norm == normalize_author(cluster.authors[0])[1],
        )
        .order_by(schema.work.c.work_id)
        .limit(1)
    ).scalar()


def load_clusters(conn: Connection, clusters: list[WorkCluster], source: str) -> LoadStats:
    stats = LoadStats()
    for cluster in clusters:
        work_id = _existing_work_id(conn, cluster)
        if work_id is None:
            genres, tags = map_subjects(cluster.subjects)
            work_id = conn.execute(
                insert(schema.work)
                .values(
                    title=cluster.title,
                    subtitle=cluster.subtitle,
                    title_norm=cluster.title_norm,
                    first_pub_year=cluster.first_pub_year,
                    description=cluster.description,
                    description_source="openlibrary" if cluster.description else "none",
                    genres=genres,
                    tags=tags,
                    low_info=cluster.description is None,
                    source=source,
                )
                .returning(schema.work.c.work_id)
            ).scalar_one()
            for position, name in enumerate(dict.fromkeys(cluster.authors), start=1):
                conn.execute(
                    insert(schema.work_author)
                    .values(work_id=work_id, author_id=_author_id(conn, name), position=position)
                    .on_conflict_do_nothing()
                )
            stats.works_created += 1
        else:
            stats.works_reused += 1

        for edition in cluster.editions:
            created = conn.execute(
                insert(schema.edition)
                .values(
                    work_id=work_id,
                    isbn13=edition.isbn13,
                    publisher=edition.publisher,
                    pub_year=edition.pub_year,
                    language=edition.language,
                    pages=edition.pages,
                    format=edition.format,
                )
                .on_conflict_do_nothing(index_elements=["isbn13"])
                .returning(schema.edition.c.edition_id)
            ).scalar()
            stats.editions_created += created is not None

    stats.catalog_version = bump_catalog_version(conn)
    return stats
