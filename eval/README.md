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

## `data/blind_sample.csv` — the agreement sample

160 Claude-graded (query, book) pairs, drawn by `scripts/blind.py draw` for a person to grade without seeing Claude's grades (`make blind-doc`, fill in `eval/blind_review.md`, `make import-blind JUDGE=<initials>`; or `make label-blind JUDGE=<initials>` in the terminal). Same columns as `qrels.csv`; the person's grades stay here, and `make agreement JUDGE=<initials>` compares them with Claude's grades as they were when the sample was drawn (`data/blind_sample_claude.csv`). `data/blind_sample_retest.csv` is the same sample graded a second time by the same person (`scripts/blind.py score --sample`). See [GRADING.md](GRADING.md#from-round-2-claudes-grades-checked-on-a-blind-sample).

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

## `data/llm_cache.jsonl` — the LLM's answers, for reproducible runs

The query parser's LLM answer for every evaluated query, one JSON line each, keyed by the model and the exact prompt messages. `make eval-parser PARSER=cascade`, `make eval PARSER=cascade` (which adds the `parsed_hybrid` system) and the negation study's `--parser cascade` read it first and only call Ollama for queries it doesn't have, so a benchmark can be rerun without the model running. A new prompt or model misses the cache by itself; old lines are never reused for it. What's cached is the model's form, not the final parse, so changes to the code after the LLM (the merge, the evidence check) apply on every run. Delete the file to force fresh answers.

## `data/conversations.yaml` — conversation set C

40 scripted sessions of 2–5 turns (design doc §27, set C): refinements, negations added over turns, references to shown books ("the second one"), topic switches with undo, the no-match dialog, "forget the page limit", small talk, and mixtures. Each turn gives what the reader types and the gold state afterwards: the whole active constraint set (PARSING.md lines; `same` for unchanged), the turn's kind and route, words the search text must keep or drop, and which shown books a reference points at. Values that depend on the catalog are never gold: `*` stands for the number a "shorter" or "darker" resolves to, and `~` skips a turn's state (which offer "yes" accepts). Several sessions test known gaps on purpose; their notes say so.

`make eval-conversations` plays every session through the conversation service on the real catalog and reports session success, turn exact match, state precision/recall/F1, kind, route and reference accuracy (`ERRORS=1` lists every miss; `PARSER=cascade` uses the LLM parser, whose answers join `llm_cache.jsonl`). `make test` validates the file. Final-turn relevance judgments (design doc: NDCG@5 on the last turn) come later, through the usual pooling.

First scores (2026-10-11, Qwen3-4B): the cascade gets 32.5% of sessions fully right, state F1 80.4%, kind 95.4%, route 96.6%, references 100%; rules alone get 5.0% and F1 34.9%, since they extract no genres or facets. The first cascade run scored 20.0% and F1 73.2%: Qwen3-4B calls bare follow-ups ("not too violent", "true crime") small talk, and the merge dropped their constraints. Most remaining misses are `fiction` not inferred from "novel", "psychological thriller" kept as its own genre, and a few phrasings the gaps sessions target.
