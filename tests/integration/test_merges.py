from sqlalchemy import Connection, insert, select, text

from shelfwise.catalog import schema
from shelfwise.evaluation.judgments import key_aliases
from shelfwise.ingest.merges import MergeDecision, apply_merges, find_candidates

from .factories import add_author, add_copy, add_edition, add_work

FIRST, SECOND, SEQUEL, OTHER = "9780000000011", "9780000000028", "9780000000035", "9780000000042"


def _book(conn: Connection, title: str, isbn: str, author_id: int, **values: object) -> int:
    work_id = add_work(conn, title, genres=values.pop("genres", None))  # type: ignore[arg-type]
    if values:
        conn.execute(schema.work.update().where(schema.work.c.work_id == work_id).values(**values))
    add_copy(conn, add_edition(conn, work_id, isbn13=isbn))
    conn.execute(insert(schema.work_author).values(work_id=work_id, author_id=author_id))
    return work_id


def _library(conn: Connection) -> dict[str, int]:
    geron, carlton = add_author(conn, "Aurélien Géron"), add_author(conn, "H. D. Carlton")
    return {
        "first": _book(conn, "Hands-On Machine Learning with Scikit-Learn and TensorFlow", FIRST,
                       geron, genres=["programming"], first_pub_year=2017),
        "second": _book(conn, "Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow",
                        SECOND, geron, genres=["artificial intelligence"], first_pub_year=2019,
                        description="Updated for TensorFlow 2."),
        "sequel": _book(conn, "Haunting Adeline", SEQUEL, carlton),
        "other": _book(conn, "Hunting Adeline", OTHER, carlton),
    }  # fmt: skip


def _pairs(conn: Connection, decisions: list[MergeDecision]) -> set[frozenset[int]]:
    return {frozenset((c.work_a, c.work_b)) for c in find_candidates(conn, decisions)}


def test_similar_titles_by_one_author_are_candidates_until_decided(conn: Connection) -> None:
    ids = _library(conn)

    assert _pairs(conn, []) >= {
        frozenset((ids["first"], ids["second"])),
        frozenset((ids["sequel"], ids["other"])),
    }
    decided = [MergeDecision(SEQUEL, OTHER, "separate")]
    assert frozenset((ids["sequel"], ids["other"])) not in _pairs(conn, decided)


def test_merge_moves_editions_fills_gaps_and_is_idempotent(conn: Connection) -> None:
    ids = _library(conn)
    conn.execute(
        insert(schema.work_facets).values(
            work_id=ids["first"], source="human", fiction=False, darkness=0
        )
    )
    decisions = [
        MergeDecision(SECOND, FIRST, "merge"),
        MergeDecision(SEQUEL, OTHER, "separate"),
    ]

    assert apply_merges(conn, decisions) == 1
    assert apply_merges(conn, decisions) == 0  # already merged

    kept = conn.execute(select(schema.work).where(schema.work.c.work_id == ids["second"])).one()
    assert kept.title.endswith("Keras, and TensorFlow")  # the kept record's title
    assert kept.first_pub_year == 2017
    assert set(kept.genres) == {"programming", "artificial intelligence"}
    assert kept.description == "Updated for TensorFlow 2."
    assert (
        conn.execute(
            select(schema.work.c.work_id).where(schema.work.c.work_id == ids["first"])
        ).first()
        is None
    )
    editions = conn.execute(
        select(schema.edition.c.isbn13).where(schema.edition.c.work_id == ids["second"])
    ).scalars()
    assert set(editions) == {FIRST, SECOND}
    facets = conn.execute(
        select(schema.work_facets.c.source).where(schema.work_facets.c.work_id == ids["second"])
    ).scalar_one()
    assert facets == "human"  # the kept work had no tags, so the human label moved over
    total = conn.execute(
        text("SELECT total_copies FROM work_availability WHERE work_id = :id"),
        {"id": ids["second"]},
    ).scalar_one()
    assert total == 2
    assert {SEQUEL, OTHER} <= {e for e in key_aliases(conn).values()}  # "separate" left alone


def test_old_keys_resolve_to_the_merged_work(conn: Connection) -> None:
    _library(conn)

    apply_merges(conn, [MergeDecision(SECOND, FIRST, "merge")])

    aliases = key_aliases(conn)
    assert aliases[FIRST] == aliases[SECOND] == FIRST  # the key is the lowest ISBN


def test_decisions_for_books_not_in_the_catalog_are_skipped(conn: Connection) -> None:
    _library(conn)

    assert apply_merges(conn, [MergeDecision("9789999999991", FIRST, "merge")]) == 0
