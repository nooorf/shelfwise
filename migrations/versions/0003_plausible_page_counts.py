"""Page counts outside 10-3000 become unknown, and the database refuses new ones.

Two Open Library editions had a page count of 1, so they passed any "under N pages" filter.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Filters read pages live, but cached results used the old counts: bump if anything changed.
    op.execute(
        """
        WITH fixed AS (
            UPDATE edition SET pages = NULL WHERE pages < 10 OR pages > 3000 RETURNING 1
        )
        UPDATE meta SET value = (value::int + 1)::text
        WHERE key = 'catalog_version' AND EXISTS (SELECT 1 FROM fixed)
        """
    )
    op.execute(
        """
        ALTER TABLE edition
            DROP CONSTRAINT ck_edition_pages_positive,
            ADD CONSTRAINT ck_edition_pages_plausible CHECK (pages BETWEEN 10 AND 3000)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE edition
            DROP CONSTRAINT ck_edition_pages_plausible,
            ADD CONSTRAINT ck_edition_pages_positive CHECK (pages > 0)
        """
    )
