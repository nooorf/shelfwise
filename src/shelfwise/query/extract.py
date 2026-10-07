"""The LLM step of query understanding (design doc §12.2, step 4).

The model fills `QueryLLM`: intent, the books it names, genres, and each mood or negation as a
named choice ("not too violent", "less", ...). Code then turns those choices into constraints
with the strengths of eval/PARSING.md. A 4B model picks the right *category* far more reliably
than it writes the right op, value and strength, and the conventions stay in one place.

Numbers, dates, availability and ISBNs are deliberately absent: the rules own them, and the
prompt lists what they found so the model leaves those words out of the semantic query.

Bump PROMPT_VERSION whenever the schema or prompt changes, so parser scores stay comparable.
"""

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from shelfwise.ingest.genres import GENRES
from shelfwise.query.constraints import Constraint

PROMPT_VERSION = "query-v2"  # v2: only listed mood words map to darkness

NOT_MENTIONED = "not mentioned"


def _genre_list(description: str) -> Any:
    # The enum goes into the JSON schema, so constrained decoding can only emit catalog genres.
    return Field(
        default_factory=list,
        description=description,
        json_schema_extra={"items": {"type": "string", "enum": list(GENRES)}},
    )


class QueryLLM(BaseModel):
    """What the LLM fills in. Every field defaults to "nothing said", so short answers are fine."""

    intent: Literal[
        "lookup", "discover", "similar", "refine", "compare", "explain", "surprise", "other"
    ] = Field(
        description="lookup: one specific book, or an author's books. similar: names a book as the "
        "reference ('like X'). discover: describes what they want. refine: only makes sense as a "
        "change to the previous results ('shorter', 'only available ones'). compare: compares "
        "books already shown. explain: asks about one book already shown. surprise: asks you to "
        "pick, no criteria. other: not a book request"
    )
    lookup_title: str | None = Field(
        default=None, description="intent lookup: the title asked for, as written; else null"
    )
    lookup_author: str | None = Field(
        default=None, description="the author whose books are wanted, as written; else null"
    )
    similar_to: list[str] = Field(
        default_factory=list, description="titles named as the reference point ('like X')"
    )
    genres: list[str] = _genre_list(
        "catalog genres the person names, synonyms mapped (sci fi -> science fiction)"
    )
    genres_strict: bool = Field(
        default=False, description="true only if they say only / must / strictly for the genre"
    )
    excluded_genres: list[str] = _genre_list("genres they don't want ('anything except romance')")
    darkness: Literal[
        "not mentioned",
        "light",
        "dark",
        "very dark",
        "not too dark",
        "not bleak",
        "darker",
        "lighter",
    ] = Field(
        default=NOT_MENTIONED,
        description="light: cozy, lighthearted, uplifting, feel-good, heartwarming, comforting. "
        "dark. very dark: disturbing, bleak, depressing. not too dark: they rule darkness out. "
        "not bleak: 'not depressing', 'isn't bleak' (dark is fine, bleak isn't). darker / "
        "lighter: than before. Other mood words (creepy, scary, hopeful) leave this unset",
    )
    romance: Literal["not mentioned", "wanted", "none or minor", "none at all", "less", "more"] = (
        Field(
            default=NOT_MENTIONED,
            description="wanted: romantic. none or minor: 'no romance', 'without romance'. "
            "none at all: 'no romance at all'. less / more: than before or than the named book",
        )
    )
    violence: Literal[
        "not mentioned", "wanted", "not too violent", "no gore", "none at all", "less", "more"
    ] = Field(
        default=NOT_MENTIONED,
        description="not too violent: 'not too violent', 'nothing violent'. no gore: 'no gore', "
        "'nothing graphic'. none at all: 'zero violence'",
    )
    pace: Literal["not mentioned", "fast", "slow", "faster", "slower"] = Field(
        default=NOT_MENTIONED, description="fast: fast paced, page turner. slow: slow burn"
    )
    supernatural: Literal["not mentioned", "wanted", "excluded"] = Field(
        default=NOT_MENTIONED,
        description="wanted: magic, ghosts, dragons. excluded: 'nothing supernatural', 'no magic', "
        "'no fantasy elements'",
    )
    historical_setting: bool = Field(
        default=False, description="true if the story should be set in a past era"
    )
    audience: Literal["not mentioned", "children", "ya", "adult"] = Field(
        default=NOT_MENTIONED, description="ya: for teens / young adult. children: for kids"
    )
    fiction: Literal["not mentioned", "fiction", "nonfiction"] = Field(
        default=NOT_MENTIONED,
        description="only if they say novel, fiction, story, or nonfiction",
    )
    reading_level: Literal["not mentioned", "intro", "intermediate", "advanced"] = Field(
        default=NOT_MENTIONED,
        description="technical or course books only. intro: beginner, from scratch, no previous "
        "knowledge. intermediate: knows some already. advanced: graduate, rigorous",
    )
    length_change: Literal["none", "shorter", "longer"] = Field(
        default="none", description="shorter / longer than before or than the named book"
    )
    year_change: Literal["none", "newer", "older"] = Field(
        default="none", description="newer / older (more modern, more recent) than before"
    )
    popular: bool = Field(
        default=False, description="true for popular, bestsellers, trending, 'best ever'"
    )
    avoid: list[str] = Field(
        default_factory=list,
        description="other things they don't want, 1-3 words each ('space', 'unreliable "
        "narrator', 'a series'); not anything already covered above",
    )
    semantic_query: str = Field(
        default="",
        description="the topic and mood words to search for. Leave out everything negated or "
        "avoided, page counts, dates, availability, and the names of books and authors",
    )

    @field_validator("genres", "excluded_genres")
    @classmethod
    def _known_genres(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(g for g in value if g in GENRES))


# Words that must not reach the semantic query once their facet is negated.
NEGATED_WORDS = {
    "romance": ("romance", "romantic", "love story"),
    "violence": ("violence", "violent", "gore", "gory", "graphic"),
    "supernatural": ("supernatural", "magic", "magical", "paranormal", "ghosts", "ghost"),
    "darkness": ("dark",),
    "bleak": ("bleak", "depressing", "depressed"),
}


def _llm(
    field: str, op: str, value: object, strength: str = "soft", exclude: bool = False
) -> Constraint:
    return Constraint.model_validate(
        {
            "field": field,
            "op": op,
            "value": value,
            "strength": strength,
            "source": "llm",
            "polarity": "exclude" if exclude else "include",
        }
    )


_DARKNESS = {
    "light": ("lte", 1, "soft"),
    "dark": ("gte", 2, "soft"),
    "very dark": ("gte", 3, "soft"),
    "not too dark": ("lte", 1, "hard"),
    "not bleak": ("lte", 2, "hard"),
    "darker": ("shift", 1, "soft"),
    "lighter": ("shift", -1, "soft"),
}
_ROMANCE = {
    "wanted": ("gte", 2, "soft"),
    "none or minor": ("lte", 1, "hard"),
    "none at all": ("eq", 0, "hard"),
    "less": ("shift", -1, "soft"),
    "more": ("shift", 1, "soft"),
}
_VIOLENCE = {
    "wanted": ("gte", 2, "soft"),
    "not too violent": ("lte", 1, "hard"),
    "no gore": ("lte", 2, "hard"),
    "none at all": ("eq", 0, "hard"),
    "less": ("shift", -1, "soft"),
    "more": ("shift", 1, "soft"),
}
_PACE = {
    "fast": ("eq", "fast"),
    "slow": ("eq", "slow"),
    "faster": ("shift", 1),
    "slower": ("shift", -1),
}


def to_constraints(out: QueryLLM) -> list[Constraint]:
    """The PARSING.md conventions, applied to the model's choices."""
    found: list[Constraint] = []
    if out.genres:
        found.append(_llm("genre", "in", out.genres, "hard" if out.genres_strict else "soft"))
    if out.excluded_genres:
        found.append(_llm("genre", "in", out.excluded_genres, "hard", exclude=True))
    for name, choice, table in (
        ("facet.darkness", out.darkness, _DARKNESS),
        ("facet.romance", out.romance, _ROMANCE),
        ("facet.violence", out.violence, _VIOLENCE),
    ):
        if choice in table:
            op, value, strength = table[choice]
            found.append(_llm(name, op, value, strength))
    if out.pace in _PACE:
        op, value = _PACE[out.pace]
        found.append(_llm("facet.pace", op, value))
    if out.supernatural == "wanted":
        found.append(_llm("facet.supernatural", "eq", "yes"))
    elif out.supernatural == "excluded":
        found.append(_llm("facet.supernatural", "eq", "yes", "hard", exclude=True))
    if out.historical_setting:
        found.append(_llm("facet.historical_setting", "eq", "yes"))
    if out.audience != NOT_MENTIONED:
        found.append(_llm("facet.audience", "eq", out.audience))
    if out.fiction != NOT_MENTIONED:
        found.append(_llm("facet.fiction", "eq", out.fiction == "fiction"))
    if out.reading_level != NOT_MENTIONED:
        found.append(_llm("facet.reading_level", "eq", out.reading_level))
    if out.length_change != "none":
        found.append(_llm("pages", "shift", -1 if out.length_change == "shorter" else 1))
    if out.year_change != "none":
        found.append(_llm("year", "shift", 1 if out.year_change == "newer" else -1))
    if out.popular:
        found.append(_llm("popular", "eq", True))
    for phrase in dict.fromkeys(" ".join(a.lower().split()) for a in out.avoid):
        if phrase:
            found.append(_llm("theme", "eq", phrase, exclude=True))
    return found


def negated_words(out: QueryLLM) -> list[str]:
    """Everything the person ruled out, as words to keep out of the semantic query."""
    words = [*out.avoid, *out.excluded_genres]
    if out.romance in ("none or minor", "none at all", "less"):
        words += NEGATED_WORDS["romance"]
    if out.violence in ("not too violent", "no gore", "none at all", "less"):
        words += NEGATED_WORDS["violence"]
    if out.supernatural == "excluded":
        words += NEGATED_WORDS["supernatural"]
    if out.darkness in ("not too dark", "lighter"):
        words += NEGATED_WORDS["darkness"]
    if out.darkness == "not bleak":
        words += NEGATED_WORDS["bleak"]
    return words


def _field_guide() -> str:
    lines = []
    for name, info in QueryLLM.model_fields.items():
        lines.append(f"- {name}: {info.description}")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You read one message sent to a library's book-search assistant and fill in \
a JSON form. Leave a field at its default unless the message says it. Never invent books, \
authors or preferences. Page counts, years and availability are handled elsewhere: ignore them.

Fields:
{_field_guide()}

Examples:
"do you have the name of the wind" -> {{"intent": "lookup", "lookup_title": "the name of the wind"}}
"a creepy gothic novel, nothing with vampires" -> {{"intent": "discover", "genres": ["gothic"], \
"fiction": "fiction", "avoid": ["vampires"], "semantic_query": "creepy gothic novel"}}
"like station eleven but less bleak" -> {{"intent": "similar", "similar_to": ["station eleven"], \
"darkness": "lighter"}}
"only sci fi for teens, no romance" -> {{"intent": "discover", "genres": ["science fiction"], \
"genres_strict": true, "audience": "ya", "romance": "none or minor", "semantic_query": "sci fi"}}
"shorter and less dark please" -> {{"intent": "refine", "length_change": "shorter", \
"darkness": "lighter"}}
"beginner guide to rust programming" -> {{"intent": "discover", "reading_level": "intro", \
"semantic_query": "rust programming guide"}}
"what are your opening hours" -> {{"intent": "other"}}"""


def build_messages(query: str, rule_spans: Sequence[str]) -> list[dict[str, str]]:
    user = f"Message: {query}"
    if rule_spans:
        user += "\nAlready handled (leave out of semantic_query): " + "; ".join(rule_spans)
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
