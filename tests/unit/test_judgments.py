from collections import Counter
from pathlib import Path

import pytest

from shelfwise.evaluation.judgments import (
    Judgment,
    PreLabel,
    drop_stale,
    load_judgments,
    load_prelabels,
    merge_pool,
    qrels_by_query,
    save_judgments,
    save_prelabels,
    set_grade,
)
from shelfwise.evaluation.splits import split_of


def test_round_trip_keeps_blanks_and_grades(tmp_path: Path) -> None:
    path = tmp_path / "qrels.csv"
    rows = [
        Judgment("M01", "9781250301697", 3, "NF", "The Silent Patient", "Alex Michaelides"),
        Judgment("M01", "9780307588371", None, "", 'Gone Girl, "a novel"', "Gillian Flynn"),
    ]

    save_judgments(path, rows)

    assert load_judgments(path) == rows


def test_prelabels_round_trip_with_reasons(tmp_path: Path) -> None:
    path = tmp_path / "prelabels.csv"
    rows = [
        PreLabel("H01", "9781250301710", 1, "claude", "the real book; no sequel exists"),
        PreLabel("A01", "9780451119674", 3, "claude"),
    ]

    save_prelabels(path, rows)

    assert load_prelabels(path) == rows


def test_missing_file_means_no_judgments(tmp_path: Path) -> None:
    assert load_judgments(tmp_path / "nope.csv") == []


def test_invalid_grade_is_reported_with_line_number(tmp_path: Path) -> None:
    path = tmp_path / "qrels.csv"
    path.write_text("query_id,work_key,grade,judge,title,author\nM01,978,5,NF,T,A\n")

    with pytest.raises(ValueError, match="line 2: grade must be 0-3"):
        load_judgments(path)


def test_merge_never_changes_existing_grades() -> None:
    existing = [Judgment("M01", "a", 3, "NF")]
    pooled = [Judgment("M01", "a"), Judgment("M01", "b")]

    merged = merge_pool(existing, pooled)

    assert merged == [Judgment("M01", "a", 3, "NF"), Judgment("M01", "b")]


def test_qrels_only_include_graded_pairs() -> None:
    judgments = [Judgment("M01", "a", 3), Judgment("M01", "b"), Judgment("M02", "c", 0)]

    assert qrels_by_query(judgments) == {"M01": {"a": 3}, "M02": {"c": 0}}


def test_grades_under_a_merged_works_old_key_still_count() -> None:
    # 978A and 978B were graded as separate works, then merged into one keyed 978A.
    aliases = {"978A": "978A", "978B": "978A"}
    rows = [Judgment("M01", "978A", 1, "NF"), Judgment("M01", "978B", 3, "NF")]

    assert qrels_by_query(rows, aliases) == {"M01": {"978A": 3}}  # the higher grade wins


def test_grades_for_books_no_longer_in_the_catalog_are_ignored() -> None:
    aliases = {"978A": "978A"}  # 978B was removed
    rows = [Judgment("M01", "978A", 2, "NF"), Judgment("M01", "978B", 3, "NF")]

    assert qrels_by_query(rows, aliases) == {"M01": {"978A": 2}}


def test_pooling_a_merged_work_again_adds_no_duplicate() -> None:
    aliases = {"978A": "978A", "978B": "978A"}
    existing = [Judgment("M01", "978B", 2, "NF")]

    assert merge_pool(existing, [Judgment("M01", "978A")], aliases) == existing


def test_stale_blanks_are_dropped_but_grades_kept() -> None:
    rows = [
        Judgment("M01", "978A", None),  # still returned
        Judgment("M01", "978B", None),  # no system returns it any more
        Judgment("M01", "978C", 2, "NF"),  # graded: always kept
    ]

    kept = drop_stale(rows, [Judgment("M01", "978A")])

    assert kept == [rows[0], rows[2]]


def test_set_grade_records_and_clears_the_judge() -> None:
    graded = set_grade([Judgment("M01", "a")], 0, 2, "NF")
    cleared = set_grade(graded, 0, None, "NF")

    assert graded[0].grade == 2 and graded[0].judge == "NF"
    assert cleared[0].grade is None and cleared[0].judge == ""


def test_split_is_deterministic_and_roughly_forty_percent_test() -> None:
    splits = Counter(split_of(f"F{i}") for i in range(2000))

    assert split_of("M01") == split_of("M01")
    assert 0.35 < splits["test"] / 2000 < 0.45
