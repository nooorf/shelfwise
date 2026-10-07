from sqlalchemy import Connection, update

from shelfwise.catalog import schema
from shelfwise.ingest.language import find_non_english

from .factories import add_edition, add_work


def _book(conn: Connection, title: str, description: str, isbn: str) -> int:
    work_id = add_work(conn, title)
    conn.execute(
        update(schema.work).where(schema.work.c.work_id == work_id).values(description=description)
    )
    add_edition(conn, work_id, isbn13=isbn)
    return work_id


def test_non_english_books_are_found_with_a_reason(conn: Connection) -> None:
    english = _book(conn, "The Silent Patient", "A famous painter shoots her husband and then "
                    "never speaks another word to anyone.", "9781250301697")  # fmt: skip
    french = _book(conn, "Five Little Pigs", "Amyas Crale, un peintre celebre, a ete assassine, "
                   "et sa femme, condamnee pour ce crime.", "9780007120871")  # fmt: skip
    edition = _book(conn, "Anges et Demons", "An ancient secret brotherhood and a devastating "
                    "new weapon of destruction.", "9780785934516")  # fmt: skip

    found = {w: reason for w, _, reason in find_non_english(conn, {"9780785934516": "French"})}

    assert english not in found
    assert found[french] == "description in 'fr'"
    assert found[edition] == "excluded edition: French"
