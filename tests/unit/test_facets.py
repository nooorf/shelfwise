import pytest
from pydantic import ValidationError

from shelfwise.tagging.facets import (
    PROMPT_VERSION,
    BookFacets,
    BookRecord,
    apply_consistency_rules,
    build_messages,
    model_version,
    normalize_themes,
)

VALID = {
    "fiction": True,
    "audience": "adult",
    "darkness": 3,
    "romance": 1,
    "violence": 2,
    "pace": "fast",
    "supernatural": "no",
    "historical_setting": "no",
    "setting_period": None,
    "reading_level": None,
    "themes": ["obsession", "trauma"],
}


def test_schema_accepts_valid_tags_and_rejects_out_of_range() -> None:
    assert BookFacets.model_validate(VALID).darkness == 3

    with pytest.raises(ValidationError):
        BookFacets.model_validate({**VALID, "darkness": 4})
    with pytest.raises(ValidationError):
        BookFacets.model_validate({**VALID, "supernatural": "maybe"})


def test_rubric_is_part_of_the_schema_sent_to_the_model() -> None:
    properties = BookFacets.model_json_schema()["properties"]

    assert (
        "Science-fiction technology is NOT supernatural"
        in properties["supernatural"]["description"]
    )
    assert "unclear" in properties["supernatural"]["enum"]
    assert "intro" in str(properties["reading_level"])


def test_messages_contain_the_record_and_truncate_long_descriptions() -> None:
    book = BookRecord(1, "Dune", ["Frank Herbert"], ["science fiction"], ["deserts"], "x" * 5000)

    system, user = build_messages(book)

    assert system["role"] == "system" and "unclear" in system["content"]
    assert "Title: Dune" in user["content"] and "Frank Herbert" in user["content"]
    assert len(user["content"]) < 1700


def test_missing_fields_are_stated_not_left_blank() -> None:
    _, user = build_messages(BookRecord(1, "Untitled", [], [], [], None))

    assert "Author: unknown" in user["content"]
    assert "Description: (no description)" in user["content"]


def test_themes_are_normalized() -> None:
    assert normalize_themes(
        ["Grief ", "grief", "Coming  of Age.", "", "x" * 60, "a", "b", "c"]
    ) == [
        "grief",
        "coming of age",
        "a",
        "b",
        "c",
    ]


def test_model_version_includes_prompt_version() -> None:
    assert model_version("qwen3:4b") == f"{PROMPT_VERSION}/qwen3:4b"


def test_consistency_rules_fix_contradictions() -> None:
    novel = BookFacets.model_validate(
        {
            **VALID,
            "reading_level": "advanced",
            "historical_setting": "no",
            "setting_period": "1920s",
        }
    )
    textbook = BookFacets.model_validate(
        {
            **VALID,
            "fiction": False,
            "historical_setting": "yes",
            "setting_period": "1990s",
            "reading_level": "intro",
        }
    )

    fixed_novel = apply_consistency_rules(novel)
    fixed_textbook = apply_consistency_rules(textbook)

    assert fixed_novel.reading_level is None and fixed_novel.setting_period is None
    assert fixed_textbook.historical_setting == "no" and fixed_textbook.setting_period is None
    assert fixed_textbook.reading_level == "intro"


def test_consistency_rules_keep_a_real_historical_setting() -> None:
    historical = BookFacets.model_validate(
        {**VALID, "historical_setting": "yes", "setting_period": "French Revolution"}
    )

    assert apply_consistency_rules(historical).setting_period == "French Revolution"


def test_themes_underscores_become_spaces() -> None:
    assert normalize_themes(["mental_health"]) == ["mental health"]
