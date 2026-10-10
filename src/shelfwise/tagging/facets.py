"""Book tags extracted by the local LLM (design doc §11.2).

These turn reader language into fields the system can filter and rank on: "nothing
supernatural" becomes `supernatural != 'yes'`, "something darker" becomes `darkness > median`,
"for a beginner" becomes `reading_level = 'intro'`. Embeddings can't do this reliably; a negated
word in a query pulls matching books *closer*.

The rubric lives in each field's description and is written into the system prompt from
there (`rubric`): Ollama's JSON schema only constrains the output's shape, the model never reads
it. "unclear" is always allowed: blurbs rarely reveal everything, and a forced yes/no produces
confident errors. Bump PROMPT_VERSION whenever the schema or prompt changes, so old and new tags
can be compared against the human labels.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

# v2: the model answers in words, themes first (v1's 0-3 digits collapsed to 0 on small models).
# v3: first-published year in the record, TAGGING.md's ~20-year historical threshold, the poetry
# rule, and reading level only for technical or course books (also enforced in code).
# v4: the year may be a reprint's (judge by the original if known); teenage books are ya even
# when the genres also say children's (qwen3:14b on v3: Gatsby "historical" from a 2019
# edition, The Fault in Our Stars "children").
# v5 (v4 scored on the 200 labels): the model says "teen" (it chose "ya" for 1 of 27 YA books),
# historical defaults to no for stories set in their own time (v4: 59 "unclear"), science
# fiction isn't supernatural, medium is the usual pace (v4: 97 of 137 medium books "slow");
# nonfiction is never supernatural and its pace is medium, in code.
# v6: the rubric is written into the system prompt. Until now it lived only in the JSON
# schema's field descriptions, which Ollama uses to constrain the output's shape but never
# shows the model: v1-v5 tagged from field names and allowed values alone (v5 still called
# Oliver Twist "historical" though the description names it as "no").
# v7: darkness by subject, with a scale of examples (v6: 54 of 74 "dark" books one step low);
# middle grade is children. Every example is a book outside the 200 hand-labelled ones (v5-v6
# named some labelled books, which would flatter their score).
PROMPT_VERSION = "facets-v7"
MAX_DESCRIPTION_CHARS = 1500
MAX_SUBJECTS = 15

YesNoUnclear = Literal["yes", "no", "unclear"]

# Genres whose books get a reading level; any other book needs the `textbook` tag (from Open
# Library's course-book subjects). "science" alone is mostly popular science, so it isn't here.
TECHNICAL_GENRES = frozenset(
    {"artificial intelligence", "programming", "computer science", "mathematics", "engineering"}
)


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
    fiction: bool = Field(
        description="true for novels, stories, graphic novels and short-story collections; a "
        "narrative poem that tells an invented story is fiction. false for nonfiction, memoirs "
        "and poetry collections"
    )
    audience: Literal["children", "teen", "adult"] = Field(
        description="children: picture books, early readers and middle-grade books for ~8-12 "
        "(Charlotte's Web, Diary of a Wimpy Kid, Percy Jackson). teen: young adult (YA) books "
        "for readers ~13-18; a teenage main character or 'young adult' in the genres means "
        "teen, even when the genres also say children's. adult: everyone else"
    )
    historical_setting: YesNoUnclear = Field(
        description="no is the usual answer: stories set in their author's own time, however "
        "long ago that is for us (Pride and Prejudice, Dracula, The Great Gatsby: no), in the "
        "present day, or in the future. yes only if the story is set at least ~20 years before "
        "it was first written (use what you know of the book; the record's year may be a later "
        "edition's): A Tale of Two Cities yes; The Book Thief (2005, set in World War II) yes; "
        "ancient Rome or medieval times in a modern book yes. unclear: only when nothing tells "
        "you when it is set. Nonfiction: no"
    )
    setting_period: str | None = Field(
        description="short name of that past era when historical_setting is yes, e.g. "
        "'French Revolution, 1789-1793'; otherwise null"
    )
    darkness: Literal["light", "some serious moments", "dark", "very dark"] = Field(
        description="judge by what the book is about, not how calmly it is told; nonfiction "
        "too. light: uplifting, gentle or comic. some serious moments: a mostly light book with "
        "a few sad or tense scenes (Wonder). dark: crime, abuse, grief, war, despair or violence "
        "are central: most thrillers, crime novels and war stories (The Kite Runner, Gone Girl). "
        "very dark: bleak or disturbing at its core: genocide, the Holocaust, torture, horror "
        "(Night by Elie Wiesel)"
    )
    romance: Literal["none", "minor subplot", "significant subplot", "central"] = Field(
        description="how much of the story is a romantic or sexual relationship; central for "
        "romance novels"
    )
    violence: Literal["none", "mild or off-page", "on-page", "graphic"]
    supernatural: YesNoUnclear = Field(
        description="yes: magic, ghosts, vampires, curses, psychic or paranormal powers. "
        "no: realistic stories, and science fiction: aliens, invisibility or time travel by "
        "science (The Time Machine, The War of the Worlds, Ender's Game) are no. Nonfiction: no"
    )
    pace: Literal["slow", "medium", "fast"] = Field(
        description="medium is the usual answer. fast: thrillers, action, page-turners. slow: "
        "only books known as slow-burning, dense or contemplative. Nonfiction: medium"
    )
    reading_level: Literal["intro", "intermediate", "advanced"] | None = Field(
        description="null unless the book is a textbook, course book or technical manual "
        "(programming, mathematics, computer science, engineering): then intro (no prior "
        "knowledge), intermediate (some background) or advanced (graduate or specialist). "
        "Fiction, memoir, biography, popular science, popular history, self-help, business "
        "and essays: null"
    )

    def to_facets(self) -> BookFacets:
        return BookFacets(
            fiction=self.fiction,
            audience="ya" if self.audience == "teen" else self.audience,
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
    first_pub_year: int | None = None


def _values(spec: dict[str, Any]) -> str:
    options: list[str] = []
    for option in spec.get("anyOf", [spec]):
        if "enum" in option:
            options += [str(v) for v in option["enum"]]
        else:
            options.append({"null": "null", "boolean": "true | false",
                            "array": "list of short phrases"}.get(option.get("type"), "text"))  # fmt: skip
    return " | ".join(options)


def rubric() -> str:
    """Every field the model fills, its allowed values and its definition, in answer order:
    the JSON schema only constrains the output, so the model reads the rules here."""
    properties = BookFacetsLLM.model_json_schema()["properties"]
    return "\n".join(
        f"- {name} ({_values(spec)}): {spec.get('description', '')}".rstrip(": ")
        for name, spec in properties.items()
    )


SYSTEM_PROMPT = (
    "You tag library books for a search system. Read the record and fill every field. "
    "Base your answers on the description and subjects, and on what you know of well-known "
    "books. Where a field allows 'unclear', use it only when the record and your knowledge "
    "really don't tell; never guess about books you don't recognise. Follow each field's "
    "definition exactly.\n\nFields:\n"
) + rubric()


def build_messages(book: BookRecord) -> list[dict[str, str]]:
    description = (book.description or "(no description)")[:MAX_DESCRIPTION_CHARS]
    record = "\n".join(
        [
            f"Title: {book.title}",
            f"Author: {', '.join(book.authors) or 'unknown'}",
            f"Year (may be a later edition): {book.first_pub_year or 'unknown'}",
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
    else:  # nonfiction has no story: no setting, nothing supernatural, pace by convention
        updates.update(historical_setting="no", supernatural="no", pace="medium")
    if updates.get("historical_setting", facets.historical_setting) != "yes":
        updates["setting_period"] = None
    return facets.model_copy(update=updates)


def is_technical(book: BookRecord) -> bool:
    return bool(TECHNICAL_GENRES.intersection(book.genres)) or "textbook" in book.subjects


def apply_record_rules(facets: BookFacets, book: BookRecord) -> BookFacets:
    """Drop answers the record gives no grounds for. Small models give general nonfiction a
    reading level (facets-v2/qwen3:4b: 52 of 81 such books tagged advanced), so it stands only
    for technical or course books."""
    facets = apply_consistency_rules(facets)
    if facets.reading_level and not is_technical(book):
        facets = facets.model_copy(update={"reading_level": None})
    return facets


def model_version(llm_model: str) -> str:
    return f"{PROMPT_VERSION}/{llm_model}"
