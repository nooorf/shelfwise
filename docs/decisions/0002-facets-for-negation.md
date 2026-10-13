# 2. Negation through LLM-extracted book facets, not the embedding

**Status:** accepted, 2026-10-06; measured 2026-10-10 · **Study:** [docs/negation-study.md](../negation-study.md)

## Context

Readers rule things out all the time: *"vampire novels without the romance"*, *"nothing supernatural"*, *"not for kids"*. Embeddings don't understand "without": the word *romance* in the query moves its vector towards romance. On this catalog, typing the negation makes every off-the-shelf system return **more** of the excluded thing than not mentioning it (dense 57% → 67% of the top 10, hybrid 51% → 62%). An off-the-shelf cross-encoder (MiniLM) doesn't fix it either (55% → 65%).

## Decision

- Tag every book once, offline, with a local LLM against a written rubric: `romance` 0–3, `violence` 0–3, `darkness` 0–3, `pace`, `supernatural`, `audience`, `fiction`, `reading_level`, `historical`. "Unclear" is a valid answer.
- The query parser turns a negation that maps to a facet into a **hard exclude** (`supernatural = yes` is dropped; `unclear` is kept with a penalty), and mood words ("dark", "fast") into soft targets.
- A negation with no facet ("nothing with animal deaths") stays a soft penalty, and the UI says "tried to avoid", not "excluded".
- Tag quality is measured, not assumed: 200 hand-reviewed books (`make score-tags`, per-facet accuracy and Cohen's kappa).

## Consequences

- On the 37 removal pairs, Shelfwise's request as typed lands at **31%** violations (from a 51% base rate) with the best ranking quality of any condition: nDCG@10 **0.55** vs 0.31 for plain hybrid.
- Filters are near perfect where the tagger is reliable and partial on graded scales, where tagger and labeller often disagree by one step. Tags against 200 hand-reviewed books (facets-v7, Qwen3-14B): audience accuracy 96% (κ 0.90), supernatural 95% (κ 0.74), fiction 100%; darkness, violence and romance 57–67% exact but 97–99% within one step (quadratic κ 0.72–0.76); pace is the weakest (κ 0.41).
- Re-tagging costs GPU time: the whole catalog was re-tagged with Qwen3-14B on the 4090 (facets-v7).
- A blind human check of 60 of the study's violation labels agreed with Claude's labels 80–100% per tag (13 of 14 disagreements one step apart).
