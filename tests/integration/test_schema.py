import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, text, update
from sqlalchemy.exc import DataError, IntegrityError

from shelfwise.catalog import schema

from .factories import add_copy, add_edition, add_work


def test_migration_matches_schema_module(engine: Engine) -> None:
    with engine.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection), schema.metadata)

    assert diffs == []


def test_extensions_and_catalog_version_seeded(conn: Connection) -> None:
    extensions = set(conn.execute(text("SELECT extname FROM pg_extension")).scalars())
    version = conn.execute(text("SELECT value FROM meta WHERE key = 'catalog_version'")).scalar()

    assert {"vector", "pg_trgm"} <= extensions
    assert version == "0"


@pytest.mark.parametrize("pages", [0, 9, 3001])
def test_implausible_page_counts_are_refused(conn: Connection, pages: int) -> None:
    work_id = add_work(conn)

    with pytest.raises(IntegrityError, match="ck_edition_pages_plausible"):
        add_edition(conn, work_id, pages=pages)


def test_isbn_is_unique(conn: Connection) -> None:
    work_id = add_work(conn)
    add_edition(conn, work_id, isbn13="9781250301697")

    with pytest.raises(IntegrityError):
        add_edition(conn, work_id, isbn13="9781250301697")


def test_copy_status_is_an_enum(conn: Connection) -> None:
    edition_id = add_edition(conn, add_work(conn))

    with pytest.raises(DataError):
        add_copy(conn, edition_id, status="missing")


def test_deleting_a_work_cascades_to_copies(conn: Connection) -> None:
    work_id = add_work(conn)
    copy_id = add_copy(conn, add_edition(conn, work_id))

    conn.execute(schema.work.delete().where(schema.work.c.work_id == work_id))

    assert (
        conn.execute(text("SELECT count(*) FROM copy WHERE copy_id = :c"), {"c": copy_id}).scalar()
        == 0
    )


def test_facet_values_are_checked(conn: Connection) -> None:
    work_id = add_work(conn)
    conn.execute(schema.work_facets.insert().values(work_id=work_id, source="llm", darkness=3))

    with pytest.raises(IntegrityError, match="ck_facets_darkness"):
        conn.execute(
            update(schema.work_facets)
            .where(schema.work_facets.c.work_id == work_id)
            .values(darkness=4)
        )


def test_embeddings_of_different_sizes_coexist(conn: Connection) -> None:
    work_id = add_work(conn)
    conn.execute(
        schema.work_embedding.insert(),
        [
            {
                "work_id": work_id,
                "model_name": "minilm",
                "content_hash": "h",
                "dim": 3,
                "embedding": [0.1, 0.2, 0.3],
            },
            {
                "work_id": work_id,
                "model_name": "qwen3",
                "content_hash": "h",
                "dim": 4,
                "embedding": [0.1, 0.2, 0.3, 0.4],
            },
        ],
    )

    dims = conn.execute(
        text("SELECT model_name, vector_dims(embedding) FROM work_embedding ORDER BY model_name")
    ).all()

    assert [tuple(row) for row in dims] == [("minilm", 3), ("qwen3", 4)]
