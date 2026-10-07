# Evaluation data

Grading rules for `data/qrels.csv`: [GRADING.md](GRADING.md). Book-tag rules for `data/facet_labels.csv`: [TAGGING.md](TAGGING.md). Parser gold rules for `data/parser_gold.yaml`: [PARSING.md](PARSING.md).

## `data/queries.csv` — query set A

One row per query. Edit freely; `make test` validates the file.

| Column | Meaning |
| --- | --- |
| `id` | Unique. Prefix by category is a convention (L = lookup, A = author, …), not a rule |
| `category` | `lookup`, `author`, `genre`, `discovery`, `multi_constraint`, `negation`, `availability`, `similarity`, `vague`, `adversarial`, `learning` (technical/course books: topic + level + goal) |
| `persona` | `student`, `casual`, `researcher`, `librarian`, `visitor` (design doc §4) |
| `family` | Paraphrases of the same need share a family; a family never spans dev and test |
| `source` | `llm-draft` (written by an LLM), `persona` (written by us), `real` (collected from people), `synthetic` (generated from a book record) |
| `text` | Exactly what the person would type or say: typos, lowercase and missing punctuation included |
| `notes` | What the query tests; not used by the code |

Rules of thumb:

- Write queries **before** looking at search results, so the set doesn't flatter the system.
- Keep `llm-draft` + `synthetic` to at most ~30% of the final set; metrics are reported per source.
- Rewriting a draft query in your own words? Change its `source` to `persona`.
- Adding a paraphrase of an existing query? Give it the same `family`.

## `data/facet_labels.csv` — human book tags

One row per (book, labeller), written by `make label-tags JUDGE=<initials>`. Books are keyed by `work_key` (lowest ISBN-13), like `qrels.csv`, so labels survive catalog rebuilds. A blank cell means "can't tell". `make score-tags` compares the LLM's tags with these: per-tag accuracy and Cohen's kappa (quadratic-weighted for ordered scales), against a majority-answer baseline.

## `data/parser_gold.yaml` — parser gold set B

The ideal parse of each query: intent, lookup, seed books, constraints, and which words must (`keep`) or must not (`drop`) reach the semantic query. Every set A query has one; set B adds about 100 more (refinements, follow-ups, hedges, negations) that carry their own text, category and source. Constraints are one line each, `[not] field op value hard|soft`; [PARSING.md](PARSING.md) has the vocabulary and the rules. `make eval-parser` scores a parser against it: intent accuracy, per-field precision/recall/F1 (strict, and ignoring strength), exact match, keep recall and the negation leak rate. Relative dates resolve against the file's `today`, so scores don't drift with the calendar. `make test` validates the file.

`data/facet_prelabels.csv` holds Claude's suggested tags for the same sample, with a note where a tag needed judgement; they become labels only once reviewed (`make tags-doc`, then `make import-tags JUDGE=<initials>`, which saves them as `<initials>-review`). See [TAGGING.md](TAGGING.md#pre-labels-and-review).

## `data/negation_queries.csv` and `data/negation_pairs.csv` — the negation study

40 pairs of queries for the negation study (design doc §40.1 B): a base request and the same request with one thing ruled out, covering supernatural, romance, violence, darkness, pace and audience. `negation_queries.csv` has the same columns as `queries.csv`; each pair shares a family, so both halves land in the same split. They're pooled and graded like set A (`make pool`, `make label` and `make grades-doc` read both files), but `make eval` scores set A only.

`negation_pairs.csv` gives each pair a `kind`: `remove` when the ruled-out thing is common in the base query's results (can the system take it out?), `lure` when it's rare there (does naming it drag it in?). The study reports the two separately. It also names, per pair, the tag value that violates the negation, written like `supernatural=yes` or `romance>=2` in the vocabulary of `facet_labels.csv`. Violations are judged from human labels, never from the LLM tags the facet filter uses.

## `data/violation_labels.csv` — human answers for the negation study

One row per (book, tag, labeller), written by `make label-violations JUDGE=<initials>`: for every book pooled for either query of a pair, the one tag that pair is about (e.g. "Supernatural?"). Same definitions as [TAGGING.md](TAGGING.md); a blank value means "can't tell". Books already labelled in full in `facet_labels.csv` by the same person aren't asked again. Kept separate from `facet_labels.csv`, whose books are a genre-balanced sample for scoring the tagger.
