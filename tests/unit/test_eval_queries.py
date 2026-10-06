from collections import Counter
from pathlib import Path

import pytest

from shelfwise.evaluation.queries import CATEGORIES, COLUMNS, load_queries

QUERIES_CSV = Path(__file__).resolve().parents[2] / "eval" / "data" / "queries.csv"


def test_committed_query_set_is_valid_and_covers_every_category() -> None:
    queries = load_queries(QUERIES_CSV)
    per_category = Counter(q.category for q in queries)

    assert len(queries) >= 50
    assert set(per_category) == set(CATEGORIES)


def write(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "q.csv"
    path.write_text("\n".join([",".join(COLUMNS), *rows]) + "\n", encoding="utf-8")
    return path


def test_loader_reports_every_problem_with_line_numbers(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Q1,lookup,student,Q1,llm-draft,do you have dune,",
        "Q1,lookups,student,Q1,llm-draft,dune,",
        "Q3,genre,teacher,,human,,",
    )

    with pytest.raises(ValueError) as error:
        load_queries(path)

    message = str(error.value)
    assert "line 3: duplicate id Q1" in message
    assert "line 3: unknown category 'lookups'" in message
    assert "line 4: unknown persona 'teacher'" in message
    assert "line 4: unknown source 'human'" in message
    assert "line 4: missing family" in message
    assert "line 4: empty text" in message


def test_loader_rejects_wrong_header(tmp_path: Path) -> None:
    path = tmp_path / "q.csv"
    path.write_text("id,text\nQ1,dune\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header must be"):
        load_queries(path)
