"""catalog_version: bumped after every catalog change so the search service knows to reload."""

from sqlalchemy import Connection, text


def get_catalog_version(conn: Connection) -> int:
    return int(
        conn.execute(text("SELECT value FROM meta WHERE key = 'catalog_version'")).scalar_one()
    )


def bump_catalog_version(conn: Connection) -> int:
    return int(
        conn.execute(
            text(
                "UPDATE meta SET value = (value::int + 1)::text "
                "WHERE key = 'catalog_version' RETURNING value"
            )
        ).scalar_one()
    )
