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
