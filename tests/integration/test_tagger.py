from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, insert, select, text

from shelfwise.catalog import schema
from shelfwise.llm.client import LLMInvalidOutput
from shelfwise.query.constraints import Constraint
from shelfwise.retrieval.filters import allowed_work_ids
from shelfwise.tagging.tagger import tag_books

from ..fakes import FakeLLM
from .factories import add_work

DARK = {
    "fiction": True, "audience": "adult", "darkness": 3, "romance": 0, "violence": 2,
    "pace": "fast", "supernatural": "no", "historical_setting": "no", "setting_period": None,
    "reading_level": None, "themes": ["Obsession", "trauma"],
}  # fmt: skip


@pytest.fixture
def engine_with_books(engine: Engine) -> Iterator[tuple[Engine, list[int]]]:
    """The tagger commits per book, so these tests use real commits and clean up after."""
    with engine.begin() as conn:
        ids = [add_work(conn, f"Tagger book {i}") for i in range(3)]
    yield engine, ids
    with engine.begin() as conn:
        conn.execute(schema.work.delete().where(schema.work.c.work_id.in_(ids)))
        conn.execute(text("DELETE FROM ingest_error WHERE source LIKE 'tagging:%'"))


def facets_of(conn: Connection, work_id: int) -> dict[str, object] | None:
    row = conn.execute(
        select(schema.work_facets).where(schema.work_facets.c.work_id == work_id)
    ).first()
    return row._asdict() if row else None


def test_tags_are_saved_with_version_and_themes(
    engine_with_books: tuple[Engine, list[int]],
) -> None:
    engine, ids = engine_with_books

    stats = tag_books(engine, FakeLLM(DARK, model="qwen3:4b"))

    assert stats.tagged >= len(ids) and stats.failed == 0
    with engine.connect() as conn:
        saved = facets_of(conn, ids[0])
        themes = conn.execute(
            select(schema.work.c.themes).where(schema.work.c.work_id == ids[0])
        ).scalar_one()
    assert saved is not None
    assert saved["darkness"] == 3 and saved["source"] == "llm"
    assert saved["model_version"] == "facets-v1/qwen3:4b"
    assert themes == ["obsession", "trauma"]


def test_rerun_skips_books_already_tagged_by_this_version(
    engine_with_books: tuple[Engine, list[int]],
) -> None:
    engine, _ = engine_with_books
    tag_books(engine, FakeLLM(DARK, model="m1"))

    assert tag_books(engine, FakeLLM(DARK, model="m1")).tagged == 0
    assert tag_books(engine, FakeLLM(DARK, model="m2")).tagged >= 3  # a new model re-tags


def test_human_labels_are_never_overwritten(engine_with_books: tuple[Engine, list[int]]) -> None:
    engine, ids = engine_with_books
    with engine.begin() as conn:
        conn.execute(
            insert(schema.work_facets).values(
                work_id=ids[0], source="human", darkness=0, supernatural="yes"
            )
        )

    tag_books(engine, FakeLLM(DARK))

    with engine.connect() as conn:
        human = facets_of(conn, ids[0])
    assert human is not None and human["source"] == "human" and human["darkness"] == 0


def test_invalid_output_is_logged_and_the_run_continues(
    engine_with_books: tuple[Engine, list[int]],
) -> None:
    engine, _ = engine_with_books
    llm = FakeLLM(LLMInvalidOutput("bad json twice"), DARK)

    stats = tag_books(engine, llm, limit=2)

    assert (stats.tagged, stats.failed) == (1, 1)
    with engine.connect() as conn:
        logged = conn.execute(
            text("SELECT count(*) FROM ingest_error WHERE source LIKE 'tagging:%'")
        ).scalar()
    assert logged == 1


def test_tags_drive_the_negation_filter(engine_with_books: tuple[Engine, list[int]]) -> None:
    engine, ids = engine_with_books
    tag_books(engine, FakeLLM({**DARK, "supernatural": "yes"}, DARK), limit=2)
    no_supernatural = Constraint(
        field="facet.supernatural",
        op="eq",
        value="yes",
        strength="hard",
        source="llm",
        polarity="exclude",
    )

    with engine.connect() as conn:
        allowed = allowed_work_ids(conn, [no_supernatural])

    assert ids[0] not in allowed  # tagged supernatural
    assert ids[1] in allowed and ids[2] in allowed  # tagged no / not tagged
