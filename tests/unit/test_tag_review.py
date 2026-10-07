from pathlib import Path
from types import SimpleNamespace

import pytest

from shelfwise.evaluation.negation import ViolationLabel, human_tags
from shelfwise.tagging.labels import FACETS, FacetLabel, load_labels
from shelfwise.tagging.review import PreLabel, load_prelabels, parse_doc, render_doc, save_prelabels

PRELABELS = Path(__file__).resolve().parents[2] / "eval" / "data" / "facet_prelabels.csv"

NOVEL = PreLabel(
    FacetLabel(
        "9780000000001",
        "claude",
        {"fiction": "yes", "audience": "adult", "darkness": "2", "romance": "1", "violence": "2",
         "pace": "slow", "supernatural": "no", "historical_setting": "yes"},
        "Victorian London",
        "A Novel",
    ),
    "set before it was written",
)  # fmt: skip
TEXTBOOK = PreLabel(
    FacetLabel("9780000000002", "claude", {"fiction": "no", "reading_level": "intro"}, "", "Calc")
)
BOOKS = {
    "9780000000001": SimpleNamespace(
        title="A Novel", authors="A. Writer", first_pub_year=2001, pages=300,
        genres=["historical fiction"], description="Fog | gaslight.",
    ),
}  # fmt: skip


def test_committed_prelabels_are_valid_and_cover_the_sample() -> None:
    prelabels = load_prelabels(PRELABELS)

    assert len(prelabels) == len({p.label.work_key for p in prelabels}) == 200
    for p in prelabels:
        for spec in FACETS:
            value = p.label.labels.get(spec.name)
            assert value is None or value in spec.values, (p.label.title, spec.name)


def test_render_then_parse_round_trips() -> None:
    doc = render_doc([NOVEL, TEXTBOOK], BOOKS, "# header\n")

    back = {b.work_key: b for b in parse_doc(doc)}

    assert back["9780000000001"].labels == NOVEL.label.labels
    assert back["9780000000001"].setting_period == "Victorian London"
    assert back["9780000000002"].labels == {"fiction": "no", "reading_level": "intro"}
    assert "| historical_setting | - |" in doc.split("## 2 ·")[1]  # doesn't apply to nonfiction
    assert "Fog \\| gaslight." in doc  # a | in the record can't break the table


def test_edits_are_read_back_and_follow_the_fiction_answer() -> None:
    doc = render_doc([NOVEL], BOOKS, "")
    doc = doc.replace("| darkness | 2 |", "| darkness | 3 |")
    doc = doc.replace("| romance | 1 |", "| romance | ? |")
    doc = doc.replace("| fiction | yes |", "| fiction | no |")  # now nonfiction
    doc = doc.replace("| reading_level | - |", "| reading_level | none |")

    (book,) = parse_doc(doc)

    assert book.labels["darkness"] == "3"
    assert "romance" not in book.labels  # can't tell
    assert "historical_setting" not in book.labels  # fiction only
    assert book.setting_period == ""
    assert book.labels["reading_level"] == "none"


def test_bad_values_are_reported_by_line() -> None:
    doc = render_doc([NOVEL], BOOKS, "").replace("| pace | slow |", "| pace | glacial |")

    with pytest.raises(ValueError, match=r"line \d+: pace must be one of slow, medium, fast"):
        parse_doc(doc)


def test_prelabels_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "pre.csv"
    save_prelabels(path, [NOVEL, TEXTBOOK])

    assert load_prelabels(path) == [NOVEL, TEXTBOOK]
    assert load_labels(tmp_path / "missing.csv") == []


def test_reviewed_labels_count_as_the_reviewers() -> None:
    reviewed = [FacetLabel("978A", "NF-review", {"romance": "2"})]
    others = [FacetLabel("978B", "XY-review", {"romance": "3"})]

    tags = human_tags([ViolationLabel("978C", "NF", "pace", "slow")], reviewed + others, "NF")

    assert tags == {"978A": {"romance": "2"}, "978C": {"pace": "slow"}}
