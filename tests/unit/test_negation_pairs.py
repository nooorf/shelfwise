from collections import Counter
from pathlib import Path

import pytest

from shelfwise.evaluation.negation import Violation, load_pairs
from shelfwise.evaluation.queries import COLUMNS, QUERY_FILES, load_query_files

ROOT = Path(__file__).resolve().parents[2]
PAIRS = ROOT / "eval" / "data" / "negation_pairs.csv"


def all_queries() -> dict:
    return {q.id: q for q in load_query_files(ROOT / p for p in QUERY_FILES)}


def test_committed_pairs_are_valid_and_cover_the_facets() -> None:
    pairs = load_pairs(PAIRS, all_queries())
    per_attribute = Counter(p.attribute for p in pairs)

    assert len(pairs) >= 40
    assert set(per_attribute) == {
        "supernatural",
        "romance",
        "violence",
        "darkness",
        "pace",
        "audience",
    }
    assert min(per_attribute.values()) >= 5


@pytest.mark.parametrize(
    ("spec", "labels", "violates"),
    [
        ("supernatural=yes", {"supernatural": "yes"}, True),
        ("supernatural=yes", {"supernatural": "no"}, False),
        ("supernatural=yes", {"supernatural": "unclear"}, None),
        ("supernatural=yes", {}, None),  # not labelled
        ("romance>=2", {"romance": "3"}, True),
        ("romance>=2", {"romance": "1"}, False),
        ("violence>=3", {"violence": "2"}, False),
        ("audience=children", {"audience": "ya"}, False),
        ("pace=slow", {"pace": "slow"}, True),
    ],
)
def test_violation_check(spec: str, labels: dict[str, str], violates: bool | None) -> None:
    assert Violation.parse(spec).check(labels) is violates


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("supernatural", "expected"),
        ("gore>=2", "unknown tag"),
        ("romance>=5", "no value"),
        ("pace>=slow", ">= only works"),
    ],
)
def test_violation_parse_rejects(spec: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Violation.parse(spec)


def write_queries(path: Path, *rows: str) -> Path:
    path.write_text("\n".join([",".join(COLUMNS), *rows]) + "\n", encoding="utf-8")
    return path


def test_pairs_must_match_their_queries(tmp_path: Path) -> None:
    queries = load_query_files(
        [
            write_queries(
                tmp_path / "q.csv",
                "Y1B,genre,casual,Y1,llm-draft,vampire novels,",
                "Y1N,negation,casual,Y2,llm-draft,vampire novels without romance,",
                "Y3N,genre,casual,Y3,llm-draft,no romance,",
            )
        ]
    )
    pairs = tmp_path / "pairs.csv"
    pairs.write_text(
        "pair,attribute,violation,base,negated\n"
        "Y1,romance,romance>=2,Y1B,Y1N\n"
        "Y2,romance,supernatural=yes,Y1B,Y3N\n"
        "Y3,romance,romance>=2,Y9B,Y3N\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error:
        load_pairs(pairs, {q.id: q for q in queries})

    message = str(error.value)
    assert "(Y1): base and negated must share a family" in message
    assert "(Y2): violation is about supernatural, not romance" in message
    assert "(Y2): Y3N must have category negation" in message
    assert "(Y3): unknown query id Y9B" in message


def test_query_ids_are_unique_across_files(tmp_path: Path) -> None:
    a = write_queries(tmp_path / "a.csv", "Q1,genre,casual,Q1,llm-draft,horror,")
    b = write_queries(tmp_path / "b.csv", "Q1,genre,casual,Q1,llm-draft,romance,")

    with pytest.raises(ValueError, match="Q1 is in both"):
        load_query_files([a, b])
