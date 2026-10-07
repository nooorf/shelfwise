from pathlib import Path

import pytest

from shelfwise.ingest.merges import MergeDecision, load_decisions, save_decisions


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "work_merges.csv"
    rows = [
        MergeDecision("9781098122461", "9781491962299", "merge", "Hands-On ML, 3rd", "Hands-On ML"),
        MergeDecision("9781957635101", "9781638932925", "separate", "Haunting Adeline", ""),
    ]

    save_decisions(path, rows)

    assert load_decisions(path) == rows


def test_missing_file_means_no_decisions(tmp_path: Path) -> None:
    assert load_decisions(tmp_path / "nope.csv") == []


def test_unknown_decision_is_reported_with_line_number(tmp_path: Path) -> None:
    path = tmp_path / "work_merges.csv"
    path.write_text("keep_isbn,other_isbn,decision,keep_title,other_title\n978,979,maybe,,\n")

    with pytest.raises(ValueError, match="line 2: decision must be merge or separate"):
        load_decisions(path)
