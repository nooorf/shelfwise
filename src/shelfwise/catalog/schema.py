"""Catalog schema as SQLAlchemy Core tables.

Three levels: a *work* is what a reader means by "a book" (recommended, embedded), an *edition*
is what an ISBN identifies (pages, year, language), and a *copy* is a physical item whose status
is the only source of availability. Migrations in `migrations/` must match these definitions;
`tests/integration/test_schema.py` fails on drift.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, ENUM, JSONB

from shelfwise.ingest.records import MAX_PAGES, MIN_PAGES

metadata = MetaData()

COPY_STATUSES = (
    "available",
    "on_loan",
    "on_hold",
    "in_transit",
    "reference_only",
    "repair",
    "lost",
)
copy_status = ENUM(*COPY_STATUSES, name="copy_status", create_type=False)

# Where a work came from: the real scanned shelf, the bulk public-data import, or manual entry.
WORK_SOURCES = ("seed", "import", "manual")

work = Table(
    "work",
    metadata,
    Column("work_id", BigInteger, Identity(), primary_key=True),
    Column("title", Text, nullable=False),
    Column("subtitle", Text),
    Column("title_norm", Text, nullable=False),
    Column("first_pub_year", Integer),
    Column("original_language", Text),
    Column("description", Text),
    Column("description_source", Text),
    Column("genres", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("themes", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("tags", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("popularity", REAL, nullable=False, server_default=text("0")),
    Column("low_info", Boolean, nullable=False, server_default=text("false")),
    Column("source", Text, nullable=False, server_default=text("'import'")),
    Column("search_text", Text),
    Column("content_hash", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "description_source IN ('catalog', 'openlibrary', 'none')",
        name="ck_work_description_source",
    ),
    CheckConstraint("source IN ('seed', 'import', 'manual')", name="ck_work_source"),
    CheckConstraint("popularity >= 0 AND popularity <= 1", name="ck_work_popularity"),
)
Index(
    "ix_work_title_norm_trgm",
    work.c.title_norm,
    postgresql_using="gin",
    postgresql_ops={"title_norm": "gin_trgm_ops"},
)
Index("ix_work_genres", work.c.genres, postgresql_using="gin")

author = Table(
    "author",
    metadata,
    Column("author_id", BigInteger, Identity(), primary_key=True),
    Column("display", Text, nullable=False),
    Column("name_norm", Text, nullable=False, unique=True),
)
Index(
    "ix_author_name_norm_trgm",
    author.c.name_norm,
    postgresql_using="gin",
    postgresql_ops={"name_norm": "gin_trgm_ops"},
)

work_author = Table(
    "work_author",
    metadata,
    Column("work_id", BigInteger, ForeignKey("work.work_id", ondelete="CASCADE"), primary_key=True),
    Column("author_id", BigInteger, ForeignKey("author.author_id"), primary_key=True),
    Column("role", Text, primary_key=True, server_default=text("'author'")),
    Column("position", SmallInteger, nullable=False, server_default=text("1")),
)
Index("ix_work_author_author_id", work_author.c.author_id)

edition = Table(
    "edition",
    metadata,
    Column("edition_id", BigInteger, Identity(), primary_key=True),
    Column("work_id", BigInteger, ForeignKey("work.work_id", ondelete="CASCADE"), nullable=False),
    Column("isbn13", CHAR(13), unique=True),
    Column("publisher", Text),
    Column("pub_year", Integer),
    Column("edition_stmt", Text),
    Column("language", Text, nullable=False, server_default=text("'en'")),
    Column("pages", Integer),
    Column("format", Text),
    CheckConstraint(
        f"pages BETWEEN {MIN_PAGES} AND {MAX_PAGES}", name="ck_edition_pages_plausible"
    ),
)
Index("ix_edition_work_id", edition.c.work_id)

copy = Table(
    "copy",
    metadata,
    Column("copy_id", BigInteger, Identity(), primary_key=True),
    Column(
        "edition_id",
        BigInteger,
        ForeignKey("edition.edition_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("barcode", Text, nullable=False, unique=True),
    Column("branch", Text, nullable=False),
    Column("floor", Text),
    Column("call_number", Text),
    Column("status", copy_status, nullable=False),
    Column("due_date", Date),
    Column("status_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_copy_edition_status", copy.c.edition_id, copy.c.status)

work_facets = Table(
    "work_facets",
    metadata,
    Column("work_id", BigInteger, ForeignKey("work.work_id", ondelete="CASCADE"), primary_key=True),
    Column("darkness", SmallInteger),
    Column("romance", SmallInteger),
    Column("violence", SmallInteger),
    Column("pace", Text),
    Column("supernatural", Text),
    Column("audience", Text),
    Column("fiction", Boolean),
    Column("historical_setting", Text),
    Column("setting_period", Text),  # free text, e.g. "French Revolution, 1789-1793"
    Column("reading_level", Text),  # technical/course books only
    Column("source", Text, nullable=False),
    Column("model_version", Text),  # e.g. "facets-v1/qwen3:4b"; null for human labels
    Column("confidence", REAL),
    Column("tagged_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("darkness BETWEEN 0 AND 3", name="ck_facets_darkness"),
    CheckConstraint("romance BETWEEN 0 AND 3", name="ck_facets_romance"),
    CheckConstraint("violence BETWEEN 0 AND 3", name="ck_facets_violence"),
    CheckConstraint("pace IN ('slow', 'medium', 'fast')", name="ck_facets_pace"),
    CheckConstraint("supernatural IN ('yes', 'no', 'unclear')", name="ck_facets_supernatural"),
    CheckConstraint("audience IN ('children', 'ya', 'adult')", name="ck_facets_audience"),
    CheckConstraint(
        "historical_setting IN ('yes', 'no', 'unclear')", name="ck_facets_historical_setting"
    ),
    CheckConstraint(
        "reading_level IN ('intro', 'intermediate', 'advanced')", name="ck_facets_reading_level"
    ),
    CheckConstraint("source IN ('llm', 'human')", name="ck_facets_source"),
)

# Dimension-free vector column: the ablation stores models of different sizes side by side.
work_embedding = Table(
    "work_embedding",
    metadata,
    Column("work_id", BigInteger, ForeignKey("work.work_id", ondelete="CASCADE"), primary_key=True),
    Column("model_name", Text, primary_key=True),
    Column("content_hash", Text, nullable=False),
    Column("dim", SmallInteger, nullable=False),
    Column("embedding", Vector(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Access-controlled; the assistant's code paths never read it.
loan = Table(
    "loan",
    metadata,
    Column("loan_id", BigInteger, Identity(), primary_key=True),
    Column("copy_id", BigInteger, ForeignKey("copy.copy_id", ondelete="CASCADE"), nullable=False),
    Column("patron_hash", Text, nullable=False),
    Column("checkout_at", DateTime(timezone=True), nullable=False),
    Column("due_at", Date, nullable=False),
    Column("returned_at", DateTime(timezone=True)),
)
Index("ix_loan_copy_id", loan.c.copy_id)

meta = Table(
    "meta",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

ingest_error = Table(
    "ingest_error",
    metadata,
    Column("ingest_error_id", BigInteger, Identity(), primary_key=True),
    Column("source", Text, nullable=False),
    Column("record_ref", Text),
    Column("reason", Text, nullable=False),
    Column("payload", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
