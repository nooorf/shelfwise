from collections import Counter

import pytest

from shelfwise.evaluation.blind import Candidate, draw, parse_doc, score


def _candidates() -> list[Candidate]:
    return [
        Candidate(f"{cat}{q}", f"k{q}-{b}", cat, grade)
        for cat in ("discovery", "negation", "author")
        for q in range(10)
        for b, grade in enumerate((0, 0, 1, 2, 3))
    ]


def test_draw_balances_grades_and_skips_mechanical_categories() -> None:
    sample = draw(_candidates(), per_grade=6, seed=1)
    assert Counter(c.suggested for c in sample) == {0: 6, 1: 6, 2: 6, 3: 6}
    assert all(c.category != "author" for c in sample)
    assert max(Counter(c.query_id for c in sample).values()) <= 2


def test_draw_is_reproducible_and_takes_what_a_grade_has() -> None:
    few = [Candidate("Q1", "a", "vague", 3), Candidate("Q2", "b", "vague", 0)]
    assert draw(few, per_grade=5, seed=7) == draw(few, per_grade=5, seed=7)
    assert len(draw(few, per_grade=5, seed=7)) == 2


def test_score_counts_only_pairs_both_graded() -> None:
    person = {("Q1", "a"): 3, ("Q1", "b"): 0, ("Q2", "c"): 1}
    claude = {("Q1", "a"): 2, ("Q1", "b"): 0, ("Q2", "c"): 1, ("Q2", "d"): 3}
    result = score(person, claude, {"Q1": "vague", "Q2": "negation"})
    assert result.pairs == 3
    assert result.exact == pytest.approx(2 / 3)
    assert result.within_one == 1.0
    assert result.confusion[(3, 2)] == 1
    assert result.by_category["vague"] == (2, 0.5)


def test_parse_doc_reads_filled_and_empty_cells() -> None:
    doc = "\n".join(
        [
            "## S11 · discovery",
            "| Grade | Book | ISBN |",
            "| --- | --- | --- |",
            "| 2 | **Salem's Lot** — Stephen King | 9780450031069 |",
            "|  | **Carrie** — Stephen King | 9780307743664 |",
            "## X01N · negation",
            "| maybe | **Dracula** — Bram Stoker | 9780486411095 |",
        ]
    )
    grades, problems = parse_doc(doc)
    assert grades == {("S11", "9780450031069"): 2, ("S11", "9780307743664"): None}
    assert problems == ["line 7: grade must be 0, 1, 2, 3 or empty, got 'maybe'"]
