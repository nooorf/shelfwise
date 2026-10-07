from pathlib import Path

import pytest

from shelfwise.tagging.facets import BookFacets
from shelfwise.tagging.labels import (
    FACET_BY_NAME,
    FacetLabel,
    agreement_by_tag,
    labelling_order,
    load_labels,
    save_labels,
    upsert_label,
)

NOVEL = {"fiction": "yes", "audience": "adult", "darkness": "3", "romance": "0",
         "violence": "2", "pace": "fast", "supernatural": "no", "historical_setting": "no"}  # fmt: skip
TEXTBOOK = {"fiction": "no", "audience": "adult", "darkness": "0", "romance": "0",
            "violence": "0", "pace": "medium", "supernatural": "no", "reading_level": "intro"}  # fmt: skip


def test_round_trip_keeps_blanks_as_cant_tell(tmp_path: Path) -> None:
    path = tmp_path / "facet_labels.csv"
    rows = [
        FacetLabel("9781250301697", "NF", NOVEL, "", "The Silent Patient"),
        FacetLabel("9780141439600", "NF", {"fiction": "yes", "historical_setting": "yes"},
                   "French Revolution", 'A Tale of Two Cities, "a novel"'),
    ]  # fmt: skip

    save_labels(path, rows)

    assert load_labels(path) == rows


def test_invalid_value_is_reported_with_line_number(tmp_path: Path) -> None:
    path = tmp_path / "facet_labels.csv"
    header = "work_key,judge,fiction,audience,darkness,romance,violence,pace,supernatural,"
    header += "historical_setting,reading_level,setting_period,title\n"
    path.write_text(header + "978,NF,yes,adult,5,,,,,,,,T\n")

    with pytest.raises(ValueError, match="line 2: darkness"):
        load_labels(path)


def test_relabelling_replaces_only_that_judges_row() -> None:
    rows = [FacetLabel("978", "NF", NOVEL), FacetLabel("978", "XY", NOVEL)]

    updated = upsert_label(rows, FacetLabel("978", "NF", TEXTBOOK))

    assert len(updated) == 2
    assert {r.judge: r.labels for r in updated} == {"NF": TEXTBOOK, "XY": NOVEL}


def test_tag_values_match_the_llm_schema() -> None:
    # The human options must be exactly what the tagger can store, or kappa compares apples
    # with pears.
    schema = BookFacets.model_json_schema()["properties"]
    assert FACET_BY_NAME["audience"].values == tuple(schema["audience"]["enum"])
    assert FACET_BY_NAME["pace"].values == tuple(schema["pace"]["enum"])
    assert FACET_BY_NAME["supernatural"].values == tuple(schema["supernatural"]["enum"])
    level = next(o for o in schema["reading_level"]["anyOf"] if "enum" in o)["enum"]
    assert FACET_BY_NAME["reading_level"].values == (*level, "none")


def test_setting_applies_to_fiction_and_reading_level_to_nonfiction() -> None:
    setting, level = FACET_BY_NAME["historical_setting"], FACET_BY_NAME["reading_level"]

    assert setting.applies(NOVEL) and not level.applies(NOVEL)
    assert level.applies(TEXTBOOK) and not setting.applies(TEXTBOOK)
    assert not setting.applies({}) and not level.applies({})  # fiction unknown: ask neither


def test_option_keys_are_unique_and_parse() -> None:
    for spec in FACET_BY_NAME.values():
        keys = [k for k, _, _ in spec.options]
        assert len(keys) == len(set(keys)), spec.name
        assert not {"?", "b", "s", "q"} & set(keys), spec.name  # reserved for commands
    assert FACET_BY_NAME["fiction"].parse("n") == "no"
    assert FACET_BY_NAME["darkness"].parse("x") is None


def test_labelling_order_interleaves_genres_and_is_stable() -> None:
    books = {f"f{i}": "fantasy" for i in range(4)} | {f"r{i}": "romance" for i in range(2)}

    order = labelling_order(books)

    assert sorted(order) == sorted(books)
    assert {k[0] for k in order[:2]} == {"f", "r"}  # first two come from different genres
    assert {k[0] for k in order[2:4]} == {"f", "r"}
    assert labelling_order(dict(reversed(books.items()))) == order


def test_agreement_skips_cant_tell_and_tags_that_dont_apply() -> None:
    human = {"a": NOVEL, "b": TEXTBOOK, "c": {"fiction": "yes"}}
    llm = {
        "a": NOVEL | {"darkness": "2", "reading_level": "none"},
        "b": TEXTBOOK | {"historical_setting": "no"},
        "c": NOVEL,
    }

    result = agreement_by_tag(human, llm)

    assert result["fiction"]["n"] == 3 and result["fiction"]["accuracy"] == 1.0
    assert result["darkness"]["n"] == 2  # "c" is can't-tell for darkness
    assert result["darkness"]["within_one"] == 1.0
    assert result["historical_setting"]["n"] == 1  # fiction only: the textbook is left out
    assert result["reading_level"]["n"] == 1  # nonfiction only
    assert result["audience"]["majority"] == 1.0
