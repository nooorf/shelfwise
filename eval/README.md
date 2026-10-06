# Evaluation data

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
