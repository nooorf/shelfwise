# Parser gold rules (set B)

`data/parser_gold.yaml` holds the ideal parse of each query: what the query parser should output for that one message, with no conversation before it. `make eval-parser` scores a parser against it. These rules keep the gold consistent. When a rule feels wrong, change the rule here and every row it affects, not just one row.

## A row

```yaml
- id: M01                       # a set A id: text, category and family come from queries.csv
  intent: discover
  constraints:
    - genre in [mystery] soft
    - pages lt 300 hard
    - year gt 2015 hard
  keep: [mystery]               # must survive into the semantic query
  drop: []                      # must NOT appear in it (negated words)

- id: BN02                      # a set B query carries its own text, category and source
  text: fantasy but no magic
  category: negation
  source: llm-draft
  intent: discover
  constraints:
    - genre in [fantasy] soft
    - not facet.supernatural eq yes hard
  keep: [fantasy]
  drop: [magic]
```

Optional keys: `lookup: {title: ..., author: ...}`, `seeds: [...]`, `family` (defaults to the id; paraphrases share one), `notes`.

A constraint is one line: `[not] field op value hard|soft`. `not` means polarity exclude. Lists are `[a, b]`. Titles, authors, seeds and keep/drop phrases accept alternatives: `1984 | Nineteen Eighty-Four`.

## Intent

| Intent | When | Example |
| --- | --- | --- |
| `lookup` | One specific book (title or ISBN), or an author's books with nothing beyond filters | "do you have dune", "anything by stephen king", "is the shining checked out" |
| `similar` | Names a book as the reference point | "like gone girl but less romance", "loved the hunger games, what next" |
| `discover` | Describes what they want | "dark psychological thriller under 300 pages" |
| `refine` | Only makes sense as a change to the previous results | "something shorter", "only ones I can borrow today" |
| `compare` | Compares books already shown | "which of these is the scariest" |
| `explain` | Asks about one book already shown | "why did you pick the second one" |
| `surprise` | Asks you to choose, with no criteria | "surprise me" |
| `other` | Not a book request | "hi", "when do you close", an injection attempt with no book in it |

## Lookup and seeds

- Write the canonical title and the author's full name, not the typed spelling: `harry poter half blood prince` → `Harry Potter and the Half-Blood Prince`. Fixing typos is the entity linker's job.
- A title lookup carries **no** `available_now`: copy status is always shown for a looked-up book, so "is X available" needs no filter. An author lookup lists many books, so it does carry one.
- An ISBN is a constraint (`isbn in [...] hard`, as ISBN-13), not a lookup title.

## Constraint fields

| Field | Ops | Values | From |
| --- | --- | --- | --- |
| `pages` | lt lte gt gte approx shift | number | "under 300 pages", "short" |
| `year` | lt lte gt gte eq shift | year of first publication | "after 2015", "the 90s", "recent" |
| `available_now` | eq | true | "available", "can take home today" |
| `isbn` | in | ISBN-13 list | a typed ISBN |
| `genre` | in | catalog genres (below) | a named genre |
| `facet.darkness` / `facet.romance` / `facet.violence` | eq lte gte shift | 0–3 | moods, negations |
| `facet.pace` | eq shift | slow, medium, fast | "fast paced", "slow burn" |
| `facet.supernatural` | eq | yes, no | "nothing supernatural", "with magic" |
| `facet.historical_setting` | eq | yes, no | "set in Victorian London" |
| `facet.audience` | eq | children, ya, adult | "for teens", "for kids" |
| `facet.fiction` | eq | true, false | "novel", "nonfiction" |
| `facet.reading_level` | eq | intro, intermediate, advanced | technical books only: "beginner", "graduate" |
| `theme` | eq | short phrase | a negation with no facet: `not theme eq space soft` |
| `title` | eq | a title | excluding a book: "other than 1984" |
| `popular` | eq | true | "popular", "bestsellers", "best ever" |

`shift` means "more" (+1) or "less" (−1) than what was shown or than the seed book: "shorter" is `pages shift -1 soft`, "darker" is `facet.darkness shift 1 soft`.

Catalog genres: psychological thriller, thriller, mystery, detective, crime, true crime, horror, fantasy, science fiction, dystopian, romance, historical fiction, literary fiction, classics, adventure, humor, short stories, poetry, drama, graphic novels, gothic, war, biography, memoir, artificial intelligence, programming, computer science, mathematics, engineering, history, science, philosophy, psychology, self-help, business, politics, religion, travel, essays. (Also young adult and children's, but audience words go to `facet.audience`, never to genre.)

## Which constraints, and how strong

**Numbers, dates and availability** follow the rule parser's conventions:

- An explicit bound is hard: "under 300 pages" → `pages lt 300 hard`; "after 2015" → `year gt 2015 hard`; "since 2015" → `gte`.
- A bare count is a soft target: "a 100 page book" → `pages approx 100 soft`.
- Vague size or recency is soft: short / quick read / finish in a weekend / not too long → `pages lte 250 soft`; long / epic / chunky → `pages gte 450 soft`; recent / latest / published recently → `year gte <today − 5> soft`.
- A decade is two hard bounds: "the 90s" → `year gte 1990` + `year lte 1999`. A century likewise: "the 1800s" → 1800–1899. A decade after "set in" describes the story, not the publication date.
- "the last 10 years" counts back from `today` at the top of the file.
- A hedge (ideally, preferably, maybe, if possible) makes the constraint it's attached to soft.
- When an explicit bound and a vague word name the same field, keep only the explicit one: "a short horror book under 250 pages" → just `pages lt 250 hard`.
- "I don't care if it's checked out" → no `available_now`.

**Everything else is soft**, except for the two cases below:

- A **named genre** → `genre in [...] soft`. Genre labels in the catalog are too incomplete to filter on. "only" / "must" / "strictly" → hard. Map synonyms and subgenres onto the vocabulary (sci fi → science fiction; cyberpunk → science fiction; cozy mystery → mystery; funny → humor) and keep the specific word in `keep`. Topics are not genres: "a book about history" → `genre in [history]` (it's in the vocabulary), but "data structures" stays in the semantic query.
- **Moods map to the facet they name**: dark → `darkness gte 2`; very dark, disturbing, bleak → `gte 3`; cozy, light, uplifting, feel-good, comforting → `darkness lte 1`; fast paced, page turner → `pace eq fast`; slow burn → `pace eq slow`; romantic → `romance gte 2`; with magic, dragons, ghosts → `supernatural eq yes`. Words with no facet ("twisty", "sad", "emotional") go only in the semantic query.
- **Audience**: for teens / YA → `ya`; for kids → `children`; for adults → `adult`.
- **Fiction**: only when the person says it (novel, fiction, story, nonfiction).
- **Reading level**: only for learning and technical requests. beginner / from scratch / intro / gentle / no previous knowledge → `intro`; know some already → `intermediate`; graduate / rigorous / advanced → `advanced`.

**Negations that map to a facet are hard** (design doc §12.4):

- "nothing supernatural", "no magic" → `not facet.supernatural eq yes hard`.
- "no romance", "without romance", "not too violent", "nothing too dark" → `<facet> lte 1 hard` (none or minor: a passing mention shouldn't disqualify a book).
- "no romance at all", "zero violence" → `eq 0 hard`.
- "no gore", "nothing graphic" → `facet.violence lte 2 hard` (on-page violence is fine, graphic isn't).
- "less romance", "less violent" (relative to a seed or the last results) → `shift -1 soft`.
- A negated genre → `not genre in [...] hard`: "anything except romance".

**Negations with no facet are soft theme penalties**: "not space stuff" → `not theme eq space soft`; "where the dog doesn't die" → `not theme eq dog dies soft`. Not a series / standalone → `not theme eq series soft` (the catalog has no series data yet).

## keep and drop

- `keep`: the topic and mood words that must reach the semantic query, so embedding search sees them. Use alternatives for words the parser may rephrase: `sci fi | science fiction`. Plurals match automatically.
- `drop`: every negated word. If "supernatural" survives into the semantic query, embedding search pulls supernatural books *closer*: this is the leak the metric counts.
- Lookups, compare, explain, surprise and other usually have neither.

## Not modelled (leave it to the semantic query, and add a note)

Edition preferences ("an older edition"), physical location ("on the second floor"), sequels ("the sequel to X" is a lookup of X; whether a sequel exists is the grounding set's problem), author gender and nationality.
