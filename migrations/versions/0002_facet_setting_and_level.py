"""Book tags: historical setting, setting period, reading level, tagged_at.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE work_facets
            ADD COLUMN historical_setting TEXT,
            ADD COLUMN setting_period TEXT,
            ADD COLUMN reading_level TEXT,
            ADD COLUMN tagged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ADD CONSTRAINT ck_facets_historical_setting
                CHECK (historical_setting IN ('yes', 'no', 'unclear')),
            ADD CONSTRAINT ck_facets_reading_level
                CHECK (reading_level IN ('intro', 'intermediate', 'advanced'))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE work_facets
            DROP CONSTRAINT ck_facets_reading_level,
            DROP CONSTRAINT ck_facets_historical_setting,
            DROP COLUMN tagged_at,
            DROP COLUMN reading_level,
            DROP COLUMN setting_period,
            DROP COLUMN historical_setting
        """
    )
