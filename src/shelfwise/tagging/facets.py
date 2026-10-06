"""Book tags extracted by the local LLM (design doc §11.2).

These turn reader language into fields the system can filter and rank on: "nothing
supernatural" becomes `supernatural != 'yes'`, "something darker" becomes `darkness > median`,
"for a beginner" becomes `reading_level = 'intro'`. Embeddings can't do this reliably; a negated
word in a query pulls matching books *closer*.

The rubric lives in each field's description, so the JSON schema Ollama enforces also tells the
model what every value means. "unclear" is always allowed: blurbs rarely reveal everything, and a
forced yes/no produces confident errors. Bump PROMPT_VERSION whenever the schema or prompt
changes, so old and new tags can be compared against the human labels.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

# v2: the model answers in words, themes first (v1's 0-3 digits collapsed to 0 on small models).
PROMPT_VERSION = "facets-v2"
MAX_DESCRIPTION_CHARS = 1500
MAX_SUBJECTS = 15

YesNoUnclear = Literal["yes", "no", "unclear"]


class BookFacets(BaseModel):
    """Tags as stored and used by filters and the ranker (0-3 scales)."""

    fiction: bool = Field(description="true for novels and stories; false for nonfiction")
    audience: Literal["children", "ya", "adult"] = Field(
        description="children: under ~12; ya: teenage readers; adult: everyone else"
    )
    darkness: int = Field(
        ge=0,
        le=3,
        description="0 light or uplifting; 1 some serious moments; 2 dark themes such as crime, "
        "grief or violence are central; 3 bleak, disturbing or horror-level",
    )
    romance: int = Field(
        ge=0,
        le=3,
        description="0 none; 1 a minor subplot; 2 a significant subplot; 3 the central story",
    )
    violence: int = Field(
        ge=0,
        le=3,
        description="0 none; 1 mild or off-page; 2 notable on-page violence; 3 graphic or gory",
    )
    pace: Literal["slow", "medium", "fast"] = Field(
        description="how fast the story moves; nonfiction: medium unless clearly otherwise"
    )
    supernatural: YesNoUnclear = Field(
        description="yes: magic, ghosts, vampires, curses, paranormal powers. Science-fiction "
        "technology is NOT supernatural. no: realistic or scientific. unclear: can't tell"
    )
    historical_setting: YesNoUnclear = Field(
        description="yes: the story takes place in a clearly past era (e.g. the French "
        "Revolution, Victorian London, World War II). no: present day or future. "
        "unclear: can't tell. Nonfiction: no"
    )
    setting_period: str | None = Field(
        description="short name of the era when historical_setting is yes, e.g. "
        "'French Revolution, 1789-1793'; otherwise null"
    )
    reading_level: Literal["intro", "intermediate", "advanced"] | None = Field(
        description="ONLY for technical, academic or course books: intro (no prior knowledge), "
        "intermediate (some background), advanced (graduate or specialist). null for fiction "
        "and general-audience nonfiction"
    )
    themes: list[str] = Field(
        description="2 to 5 short lowercase themes, e.g. 'grief', 'obsession', 'coming of age'",
        min_length=0,
        max_length=6,
    )


DARKNESS = ("light", "some serious moments", "dark", "very dark")
ROMANCE = ("none", "minor subplot", "significant subplot", "central")
VIOLENCE = ("none", "mild or off-page", "on-page", "graphic")


class BookFacetsLLM(BaseModel):
    """What the LLM fills in. Field order matters: themes come first so the model has described
    the book before it scores it, and scales are words rather than digits, because small models
    under constrained decoding drift to the lowest digit."""

    themes: list[str] = Field(
        description="2 to 5 short lowercase themes of the book, e.g. 'grief', 'obsession', "
        "'coming of age', 'surveillance'",
        min_length=0,
        max_length=6,
    )
    fiction: bool = Field(description="true for novels and stories; false for nonfiction")
    audience: Literal["children", "ya", "adult"] = Field(
        description="children: under ~12; ya: teenage readers; adult: everyone else"
    )
    historical_setting: YesNoUnclear = Field(
        description="yes ONLY if the story is set in a period that was already the past when the "
        "book was written (e.g. the French Revolution in a 19th-century novel, World War II in a "
        "2010s novel). Stories set in the author's own present, or in the future, are no. "
        "unclear: can't tell. Nonfiction: no"
    )
    setting_period: str | None = Field(
        description="short name of that past era when historical_setting is yes, e.g. "
        "'French Revolution, 1789-1793'; otherwise null"
    )
    darkness: Literal["light", "some serious moments", "dark", "very dark"] = Field(
        description="light: uplifting or gentle. some serious moments. dark: crime, abuse, grief, "
        "despair or violence are central. very dark: bleak, disturbing, horror"
    )
    romance: Literal["none", "minor subplot", "significant subplot", "central"] = Field(
        description="how much of the story is a romantic or sexual relationship; central for "
        "romance novels"
    )
    violence: Literal["none", "mild or off-page", "on-page", "graphic"]
    supernatural: YesNoUnclear = Field(
        description="yes: magic, ghosts, vampires, curses, psychic or paranormal powers. "
        "Science-fiction technology is NOT supernatural. no: realistic or scientific"
    )
    pace: Literal["slow", "medium", "fast"] = Field(
        description="how fast the story moves; nonfiction: medium unless clearly otherwise"
    )
    reading_level: Literal["intro", "intermediate", "advanced"] | None = Field(
        description="ONLY for technical, academic or course books: intro (no prior knowledge), "
        "intermediate (some background), advanced (graduate or specialist). null for fiction "
        "and general-audience nonfiction"
    )

    def to_facets(self) -> BookFacets:
        return BookFacets(
            fiction=self.fiction,
            audience=self.audience,
            darkness=DARKNESS.index(self.darkness),
            romance=ROMANCE.index(self.romance),
            violence=VIOLENCE.index(self.violence),
            pace=self.pace,
            supernatural=self.supernatural,
            historical_setting=self.historical_setting,
            setting_period=self.setting_period,
            reading_level=self.reading_level,
            themes=self.themes,
        )


@dataclass(frozen=True)
class BookRecord:
    work_id: int
    title: str
    authors: Sequence[str]
    genres: Sequence[str]
    subjects: Sequence[str]
    description: str | None


SYSTEM_PROMPT = (
    "You tag library books for a search system. Read the record and fill every field. "
    "Base your answers on the description and subjects. You may use general knowledge of "
    "well-known books, but answer 'unclear' (or a cautious value) rather than guess about "
    "books you don't recognise. Follow each field's definition exactly."
)


def build_messages(book: BookRecord) -> list[dict[str, str]]:
    description = (book.description or "(no description)")[:MAX_DESCRIPTION_CHARS]
    record = "\n".join(
        [
            f"Title: {book.title}",
            f"Author: {', '.join(book.authors) or 'unknown'}",
            f"Genres: {', '.join(book.genres) or 'none listed'}",
            f"Subjects: {', '.join(list(book.subjects)[:MAX_SUBJECTS]) or 'none listed'}",
            f"Description: {description}",
        ]
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": record}]


def normalize_themes(themes: Sequence[str]) -> list[str]:
    cleaned = [" ".join(t.lower().replace("_", " ").split()).strip(" .,;") for t in themes]
    return list(dict.fromkeys(t for t in cleaned if 0 < len(t) <= 40))[:5]


def apply_consistency_rules(facets: BookFacets) -> BookFacets:
    """Fix answers that contradict other answers. These are logical consequences, not
    judgments, so they hold for any model: small models in particular fill every field."""
    updates: dict[str, object] = {}
    if facets.fiction:
        updates["reading_level"] = None  # reading level is for technical/course books
    else:
        updates["historical_setting"] = "no"  # nonfiction has no story setting
    if updates.get("historical_setting", facets.historical_setting) != "yes":
        updates["setting_period"] = None
    return facets.model_copy(update=updates)


def model_version(llm_model: str) -> str:
    return f"{PROMPT_VERSION}/{llm_model}"
