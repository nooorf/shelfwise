from sqlalchemy import Connection, insert

from shelfwise.catalog import schema
from shelfwise.tagging.labels import llm_labels

from .factories import add_edition, add_work


def test_llm_tags_are_read_in_label_form_and_human_rows_ignored(conn: Connection) -> None:
    novel = add_work(conn, "Labels novel")
    add_edition(conn, novel, isbn13="9780000000011")
    textbook = add_work(conn, "Labels textbook")
    add_edition(conn, textbook, isbn13="9780000000028")
    human = add_work(conn, "Labels human")
    add_edition(conn, human, isbn13="9780000000035")
    common = {"source": "llm", "model_version": "facets-v2/qwen3:4b", "audience": "adult",
              "romance": 0, "violence": 1, "pace": "fast", "supernatural": "no"}  # fmt: skip
    conn.execute(
        insert(schema.work_facets),
        [
            common | {"work_id": novel, "fiction": True, "darkness": 3,
                      "historical_setting": "unclear", "reading_level": None},
            common | {"work_id": textbook, "fiction": False, "darkness": None,
                      "historical_setting": "no", "reading_level": "intro"},
            common | {"work_id": human, "source": "human", "fiction": True, "darkness": 0,
                      "historical_setting": "no", "reading_level": None},
        ],
    )  # fmt: skip

    labels = llm_labels(conn)

    version, novel_labels = labels["9780000000011"]
    assert version == "facets-v2/qwen3:4b"
    assert novel_labels["fiction"] == "yes" and novel_labels["darkness"] == "3"
    assert novel_labels["reading_level"] == "none"
    _, textbook_labels = labels["9780000000028"]
    assert textbook_labels["reading_level"] == "intro"
    assert "darkness" not in textbook_labels  # missing value = can't tell, not "None"
    assert "9780000000035" not in labels
