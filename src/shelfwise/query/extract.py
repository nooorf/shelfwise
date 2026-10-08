"""The LLM step of query understanding (design doc §12.2, step 4).

The model fills `QueryLLM`: intent, the books it names, genres, and each mood or negation as a
named choice ("not too violent", "less", ...). Code then turns those choices into constraints
with the strengths of eval/PARSING.md. A 4B model picks the right *category* far more reliably
than it writes the right op, value and strength, and the conventions stay in one place.

Numbers, dates, availability and ISBNs are deliberately absent: the rules own them, and the
prompt lists what they found so the model leaves those words out of the semantic query.

Bump PROMPT_VERSION whenever the schema or prompt changes, so parser scores stay comparable.
"""

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from shelfwise.ingest.genres import GENRES
from shelfwise.ingest.normalize import fold_text
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


# Evidence (step 5's sanity check). On short or off-topic messages a 4B model fills in the whole
# form, often with words from the field descriptions ("hi there" -> ya, fast, supernatural,
# avoid "space"). So a choice only stands if the message has a word that could have produced
# it: the PARSING.md cue words, matched on folded text. Missing a mood costs a soft boost; a
# wrong hard constraint drops good books.
_CUES = {
    "darkness": r"dark(er|est)?|light(er)?|light ?hearted|coz(y|ier)|cosy|uplifting|feel ?good"
    r"|heart ?warming|comforting|bleak|depressing|disturbing",
    "romance": r"romance|romances|romantic|love stor(y|ies)|love triangles?",
    "violence": r"violen(t|ce)|gore|gory|graphic|brutal|bloody|gruesome",
    "pace": r"fast|faster|slow|slower|paced?|page ?turners?|slow ?burn",
    "supernatural": r"supernatural|magic(al)?|ghosts?|paranormal|dragons?|vampires?|witch(es)?"
    r"|wizards?|fae|fair(y|ies)|werewol(f|ves)|demons?|haunted|spirits?",
    "historical_setting": r"historical|history|past|eras?|century|centuries|ancient|medieval"
    r"|victorian|regency|tudor|vikings?",
    "audience": r"kids?|child|children|childrens|teens?|teenagers?|ya|young adults?|adults?"
    r"|grown ?ups?|middle grade|\d+ ?years? ?olds?",
    "fiction": r"novels?|novella|fiction|nonfiction|non ?fiction|story|stories",
    "reading_level": r"beginners?|intro|introduction|introductory|from scratch|basics|gentle"
    r"|(previous|prior) (knowledge|experience)|new to|get (me )?started|starting out"
    r"|know some|already know|intermediate|advanced|graduate|rigorous",
    "length_change": r"shorter|longer|less long|not as long|fewer pages|more pages",
    "year_change": r"newer|older|more (recent|modern|contemporary)|less (old|dated)",
    "popular": r"popular|bestsellers?|best ?sellers?|trending|best( \w+){0,3} ever|greatest"
    r"|famous|everyone",
}
# Genre names a person doesn't say verbatim (PARSING.md: map synonyms and subgenres).
_GENRE_CUES = {
    "science fiction": r"sci ?fi|sf|cyberpunk|space|aliens?|robots?|time travel",
    "mystery": r"whodunn?its?|cozy|cosy|sleuths?|detectives?",
    "detective": r"sleuths?|private eye|investigators?|whodunn?its?",
    "thriller": r"suspense|spy|spies|espionage|thrilling",
    "crime": r"murders?|heists?|mafia|mob|gangsters?|serial killers?|police",
    "horror": r"scary|creepy|ghosts?|haunted|zombies?|vampires?|monsters?",
    "fantasy": r"magic(al)?|dragons?|wizards?|witch(es)?|fae|fair(y|ies)|elves|swords? and",
    "romance": r"romantic|love stor(y|ies)|rom ?coms?",
    "humor": r"funny|comedy|comic|hilarious|laugh",
    "graphic novels": r"manga|comics?|comic books?",
    "historical fiction": r"ancient|medieval|victorian|regency|tudor|century|wartime",
    "dystopian": r"dystopia|post ?apocalyptic|apocalypse|totalitarian|surveillance",
    "war": r"wartime|soldiers?|battles?|military|world war|ww ?(1|2|i|ii)",
    "poetry": r"poems?|poets?|verse",
    "biography": r"life of|life story|autobiograph\w*",
    "memoir": r"life story|autobiograph\w*",
    "programming": r"code|coding|programs?|python|java|javascript|php|sql|mysql|rust|c|software"
    r"|web ?sites?|web|developers?|apps?",
    "computer science": r"algorithms?|data structures?|operating systems?|databases?|networks?"
    r"|networking|compilers?|computers?|computing",
    "artificial intelligence": r"ai|machine learning|deep learning|neural|llms?",
    "mathematics": r"maths?|calculus|algebra|statistics|geometry|proofs?",
    "engineering": r"circuits?|signals?|electrical|mechanical|electronics|control systems?",
    "science": r"physics|biology|chemistry|astronomy|universe|evolution|scientific",
    "business": r"startups?|management|leadership|money|finance|investing|marketing"
    r"|entrepreneurs?",
    "politics": r"political|government|democracy|elections?",
    "religion": r"faith|god|christian|islam\w*|bible|spiritual",
    "adventure": r"quests?|expeditions?|pirates?|treasure|exploring",
    "literary fiction": r"literary|book club|booker|pulitzer",
    "short stories": r"anthology|anthologies|collection of stories",
}
_GENRE_STOPWORDS = {"fiction", "novels", "and", "s"}
_FILLER_WORDS = {"a", "an", "the", "any", "books", "book", "novels", "novel", "stuff"}
# Genres that are also topics: "no war" is a theme penalty, not a genre filter (PARSING.md).
_TOPIC_GENRES = {
    "war", "history", "science", "travel", "politics", "religion", "business", "philosophy",
    "psychology", "mathematics", "engineering", "programming", "computer science",
    "artificial intelligence",
}  # fmt: skip
# Before the avoided phrase; fold_text turns "isn't" into "isn t".
_NEGATION_BEFORE = re.compile(
    r"\b(?:no|not|without|nothing|except|none|never|skip|avoid|other than|instead of"
    r"|(?:isn|aren|doesn|don|wasn|won) ?t)\b"
)
_LESS_BEFORE = re.compile(r"\bless\b")


def _says(pattern: str, text: str) -> bool:
    return re.search(rf"\b(?:{pattern})\b", text) is not None


def _names_genre(genre: str, text: str) -> bool:
    if (cues := _GENRE_CUES.get(genre)) and _says(cues, text):
        return True
    words = [w for w in fold_text(genre).split() if w not in _GENRE_STOPWORDS] or [genre]
    said = text.split()
    # Each distinctive word of the genre, or a word starting like it ("mysteries", "classic").
    return all(any(s.startswith(w[:5]) if len(w) > 4 else s in (w, w + "s") for s in said)
               for w in words)  # fmt: skip


def _position(phrase: str, text: str) -> int | None:
    """Where an avoided phrase starts in the message; its words may be spread out or inflected
    ("children harmed" in "no children are harmed"). None if any word is missing."""
    said = text.split()
    starts = [sum(len(w) + 1 for w in said[:i]) for i in range(len(said))]
    found = []
    for word in phrase.split():
        stem = word[:5] if len(word) > 4 else word
        hits = [
            i for i, s in enumerate(said) if s == word or (len(word) > 4 and s.startswith(stem))
        ]
        if not hits:
            return None
        found.append(hits[0])
    return starts[min(found)] if found else None


def _avoid_as_facet(phrase: str, less: bool) -> dict[str, str]:
    """An avoided phrase that is really a facet negation ("less violent", "not depressing")."""
    if _says(r"gore|gory|graphic", phrase):
        return {"violence": "less" if less else "no gore"}
    if _says(_CUES["violence"], phrase):
        return {"violence": "less" if less else "not too violent"}
    if _says(_CUES["romance"], phrase):
        return {"romance": "less" if less else "none or minor"}
    if _says(r"supernatural|magic(al)?|paranormal", phrase):  # not "vampires": a theme
        return {"supernatural": "excluded"}
    if _says(r"bleak|depressing|depressed", phrase):
        return {"darkness": "not bleak"}
    if _says(r"dark", phrase):
        return {"darkness": "lighter" if less else "not too dark"}
    return {}


# A mood word the message itself negates: "nothing too dark", "no romance", "isn't violent".
# Its negation beats a positive pick ("cozy" -> light) so the word is stripped and filtered.
_NEGATED_MOOD = {
    "darkness": (r"bleak|depressing", "not bleak", ("not bleak",)),
    "darkness ": (r"dark", "not too dark", ("not too dark", "not bleak", "lighter")),
    "romance": (r"romance|romantic|love story", "none or minor",
                ("none or minor", "none at all", "less")),
    "violence": (r"violen(?:t|ce)", "not too violent",
                 ("not too violent", "no gore", "none at all", "less")),
    "violence ": (r"gore|gory|graphic", "no gore",  # "isn't gory": graphic only
                  ("not too violent", "no gore", "none at all", "less")),
    "supernatural": (r"supernatural|magic(?:al)?|paranormal", "excluded", ("excluded",)),
}  # fmt: skip
_NEGATOR = r"(?:no|not|nothing|without|never|(?:isn|aren|don|doesn|wasn) ?t)"


def _negated_moods(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, (words, choice, _) in _NEGATED_MOOD.items():
        if re.search(rf"\b{_NEGATOR}(?: \w+){{0,2}} (?:{words})\b", text):
            found.setdefault(key.strip(), choice)
    return found


def check_evidence(out: QueryLLM, message: str) -> QueryLLM:
    """Reset every choice the message gives no reason for, and route avoided phrases that
    are really genres or facets to where PARSING.md puts them."""
    text = fold_text(message)
    update: dict[str, Any] = {}
    for name in ("darkness", "romance", "violence", "pace", "supernatural", "audience",
                 "fiction", "reading_level"):  # fmt: skip
        if getattr(out, name) != NOT_MENTIONED and not _says(_CUES[name], text):
            update[name] = NOT_MENTIONED
    for name in ("historical_setting", "popular"):
        if getattr(out, name) and not _says(_CUES[name], text):
            update[name] = False
    for name, choice in _negated_moods(text).items():
        negations = next(n for k, (_, _, n) in _NEGATED_MOOD.items() if k.strip() == name)
        if update.get(name, getattr(out, name)) not in negations:
            update[name] = choice
    for name in ("length_change", "year_change"):
        if getattr(out, name) != "none" and not _says(_CUES[name], text):
            update[name] = "none"
    genres = [g for g in out.genres if _names_genre(g, text)]
    excluded = [g for g in out.excluded_genres if _names_genre(g, text)]
    # Said by the genre already: "romance novels" is not also romance >= 2.
    if "romance" in genres and update.get("romance", out.romance) == "wanted":
        update["romance"] = NOT_MENTIONED
    era = _CUES["historical_setting"].replace("historical|history|", "")
    if "historical fiction" in genres and not _says(era, text):  # unless an era is named
        update["historical_setting"] = False

    avoid = []
    for phrase in dict.fromkeys(" ".join(fold_text(a).split()) for a in out.avoid):
        at = _position(phrase, text)
        if at is None:
            continue  # not in the message: copied from the form
        before = text[:at]
        less = _LESS_BEFORE.search(before[-12:]) is not None
        if not (_NEGATION_BEFORE.search(before) or less):
            continue  # said, but not ruled out ("an unreliable narrator thriller")
        facet = _avoid_as_facet(phrase, less)
        bare = " ".join(w for w in phrase.split() if w not in _FILLER_WORDS)
        genre = next(
            (g for g in GENRES if bare in (g, g + "s", g.rstrip("y") + "ies")
             and g not in _TOPIC_GENRES),
            None,
        )  # fmt: skip
        if genre is not None and not facet:
            if genre not in excluded:
                excluded.append(genre)
        elif facet:
            for name, choice in facet.items():
                if update.get(name, getattr(out, name)) == NOT_MENTIONED:
                    update[name] = choice
        else:
            avoid.append(phrase)
    update |= {"genres": genres, "excluded_genres": excluded, "avoid": avoid}
    return out.model_copy(update=update)


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
