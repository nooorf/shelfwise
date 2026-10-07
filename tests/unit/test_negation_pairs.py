from collections import Counter
from pathlib import Path

import pytest

from shelfwise.evaluation.judgments import Judgment
from shelfwise.evaluation.negation import (
    NegationPair,
    Violation,
    ViolationLabel,
    human_tags,
    load_pairs,
    load_violation_labels,
    questions,
    save_violation_labels,
    upsert_violation_label,
)
from shelfwise.evaluation.queries import COLUMNS, QUERY_FILES, load_query_files
from shelfwise.tagging.labels import FacetLabel

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
    assert sum(p.kind == "remove" for p in pairs) >= 0.9 * len(
        pairs
    )  # lure pairs are the exception


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
        "pair,attribute,violation,kind,base,negated\n"
        "Y1,romance,romance>=2,remove,Y1B,Y1N\n"
        "Y2,romance,supernatural=yes,remove,Y1B,Y3N\n"
        "Y3,romance,romance>=2,bait,Y9B,Y3N\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error:
        load_pairs(pairs, {q.id: q for q in queries})

    message = str(error.value)
    assert "(Y1): base and negated must share a family" in message
    assert "(Y2): violation is about supernatural, not romance" in message
    assert "(Y2): Y3N must have category negation" in message
    assert "(Y3): unknown query id Y9B" in message
    assert "(Y3): kind must be one of remove, lure" in message


def test_query_ids_are_unique_across_files(tmp_path: Path) -> None:
    a = write_queries(tmp_path / "a.csv", "Q1,genre,casual,Q1,llm-draft,horror,")
    b = write_queries(tmp_path / "b.csv", "Q1,genre,casual,Q1,llm-draft,romance,")

    with pytest.raises(ValueError, match="Q1 is in both"):
        load_query_files([a, b])


def test_violation_labels_round_trip_and_upsert(tmp_path: Path) -> None:
    path = tmp_path / "violations.csv"
    rows = [ViolationLabel("978A", "NF", "supernatural", "yes", "Dracula")]
    rows = upsert_violation_label(
        rows, ViolationLabel("978A", "NF", "supernatural", "no", "Dracula")
    )
    rows = upsert_violation_label(rows, ViolationLabel("978B", "NF", "romance", "", "Emma"))
    save_violation_labels(path, rows)

    loaded = load_violation_labels(path)

    assert sorted(loaded, key=lambda r: r.work_key) == [
        ViolationLabel("978A", "NF", "supernatural", "no", "Dracula"),
        ViolationLabel("978B", "NF", "romance", "", "Emma"),
    ]


def test_violation_labels_reject_bad_values(tmp_path: Path) -> None:
    path = tmp_path / "violations.csv"
    path.write_text("work_key,judge,facet,value,title\n978A,NF,romance,9,x\n978B,NF,gore,1,y\n")

    with pytest.raises(ValueError) as error:
        load_violation_labels(path)

    assert "line 2: romance must be one of" in str(error.value)
    assert "line 3: unknown tag 'gore'" in str(error.value)


def test_questions_cover_both_queries_of_a_pair_and_skip_known_books() -> None:
    pairs = [
        NegationPair("X1", "romance", Violation.parse("romance>=2"), "X1B", "X1N"),
        NegationPair("X2", "romance", Violation.parse("romance>=2"), "X2B", "X2N"),
        NegationPair("X3", "supernatural", Violation.parse("supernatural=yes"), "X3B", "X3N"),
    ]
    judgments = [
        Judgment("X1B", "978A", title="Emma"),
        Judgment("X1N", "978B", title="Persuasion"),
        Judgment("X2N", "978A-old", title="Emma"),  # merged into 978A
        Judgment("X3N", "978A", title="Emma"),
        Judgment("X3B", "978C", title="Dracula"),
        Judgment("S01", "978D", title="Not in a pair"),
    ]
    facet_labels = [FacetLabel("978C", "NF", {"supernatural": "yes"})]
    answered = [ViolationLabel("978B", "NF", "romance", "")]  # "can't tell" counts as asked
    known = human_tags(answered, facet_labels, "NF")

    asked = questions(pairs, judgments, known, aliases={"978A-old": "978A"})

    assert [(q.work_key, q.facet, q.pairs) for q in asked] == [
        ("978A", "romance", ("X1", "X2")),
        ("978A", "supernatural", ("X3",)),
    ]


def test_human_tags_are_per_judge_and_one_tag_answers_win() -> None:
    facet_labels = [
        FacetLabel("978A", "NF", {"romance": "1", "pace": "slow"}),
        FacetLabel("978A", "XY", {"romance": "3"}),
    ]
    answers = [ViolationLabel("978A", "NF", "romance", "2")]

    tags = human_tags(answers, facet_labels, "NF")

    assert tags == {"978A": {"romance": "2", "pace": "slow"}}
    assert Violation.parse("romance>=2").check({"romance": "2"}) is True
