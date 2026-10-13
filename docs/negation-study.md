# Negation in book search

*"A vampire novel without the romance." "A thriller where nothing supernatural happens." "Fantasy that isn't YA."* Readers say what they *don't* want all the time, and retrieval models are known to handle it badly: an embedding of "without romance" sits close to "romance" (the NevIR failure). This study measures how badly, on this catalog, and what fixes it at what cost.

**Short answer.** Typing the negation into a search box makes things worse than not mentioning it: every off-the-shelf system returns *more* books with the ruled-out thing (hybrid: 51% → 62% of the top 10). Stripping the negation only gets back to that base rate. What works is turning the negation into a filter on book tags, and Shelfwise's query parser does that by itself: 31% violations on the negated query as typed, with the best ranking quality of any condition (NDCG@10 0.55 against 0.31 for the plain hybrid). Filters work almost perfectly where the tagger is reliable (supernatural, audience) and only partly on graded scales (violence, darkness), where tagger and labeller disagree about the exact level.

## Setup

**Queries.** 40 pairs, each a base request and the same request with one thing ruled out, over six book tags (`eval/data/negation_queries.csv`, `eval/data/negation_pairs.csv`):

| Tag | Example pair | Counts as a violation |
| --- | --- | --- |
| supernatural | a creepy gothic novel / … with nothing supernatural, the horror should be human | `supernatural=yes` |
| romance | vampire novels / … without the romance | `romance>=2` |
| violence | a crime thriller about a serial killer / … but nothing gory | `violence>=3` (graphic only) |
| darkness | a psychological thriller about a family secret / … nothing too dark | `darkness>=2` or `>=3` |
| pace | an epic fantasy series / … that doesn't drag | `pace=slow` |
| audience | fantasy about a school for magic / … not for kids | `audience=children` |

37 are **removal** pairs: the ruled-out thing is common in the base request's results, so the question is whether a system can take it out. 3 are **lure** pairs: it's rare in the base results, so the question is whether *naming* it drags it in.

**Systems.** BM25, dense (bge-base-en-v1.5), hybrid (both, RRF), hybrid + MiniLM cross-encoder, and `parsed_hybrid` (Shelfwise: an LLM query parser turns the request into constraints first).

**Conditions.** For each system, three query texts × three ways of using the tags:

- **Query:** *raw* (the negated request as typed) or *stripped* (the base request, i.e. perfect negation removal: an upper bound on what stripping alone can do). The *base query* row is the same base request, measuring how common the ruled-out thing is anyway.
- **Tags:** *off*, *soft* (books the LLM tags flag move 10 places down), *hard* (flagged books removed; untagged books kept).

The tags the filters use come from the LLM tagger (Qwen3-14B, prompt facets-v7). **Violations are judged from separate labels**, never from those tags, or the study would grade itself.

**Labels.** Every book in the pooled results of both queries of every pair was asked one question for the pair's tag, 1,679 questions in all, labelled by Claude from each book's record and general knowledge, following `eval/TAGGING.md` (`eval/data/violation_labels.csv`, judge `claude`). A person grades a blind sample of 60 (10 per tag, Claude's answers hidden) to measure how far these labels can be trusted: see [Limitations](#limitations).

**Metrics.** violation@10 (and @5): the share of the labelled top-10 books that break the negation, averaged over pairs, with 95% bootstrap CIs. NDCG@10 on the negated query, from the benchmark's graded judgments (which grade a book with the ruled-out thing as 0, `eval/GRADING.md`). Coverage: 9.9 of the top 10 books were labelled on average.

## Results

### Removal pairs (37)

violation@10 (lower is better) and NDCG@10 on the negated request:

| System | Rate anyway (base request) | Negated, as typed | + hard filter | Stripped | Stripped + hard filter |
| --- | --- | --- | --- | --- | --- |
| BM25 | 33% | 40% | 16% | 33% | 17% |
| Dense | 57% | **67%** | 42% | 57% | 36% |
| Hybrid | 51% | **62%** | 33% | 51% | 30% |
| Hybrid + MiniLM rerank | 55% | **65%** | 35% | 55% | 32% |
| **Shelfwise (parsed_hybrid)** | 51% | **31%** | **28%** | 51% | 29% |

| System | NDCG@10, negated as typed | + hard filter | Stripped + hard filter |
| --- | --- | --- | --- |
| BM25 | 0.20 | 0.25 | 0.32 |
| Dense | 0.34 | 0.42 | 0.44 |
| Hybrid | 0.31 | 0.43 | 0.50 |
| Hybrid + MiniLM rerank | 0.28 | 0.34 | 0.42 |
| **Shelfwise (parsed_hybrid)** | **0.55** | **0.56** | 0.52 |

CIs are about ±9 points on violation rates and ±6 on NDCG (37 pairs); the full table with CIs, @5 and soft filters is in `eval/reports/20261010-233251_67933f4-dirty_negation-study.json`.

What the table says:

1. **Typing the negation makes it worse.** On every embedding-based system the negated request returns *more* violating books than the base request (dense 57% → 67%, hybrid 51% → 62%, reranker 55% → 65%): "without the romance" moves the query vector *toward* romance. BM25 gets worse too, by less (33% → 40%).
2. **The off-the-shelf reranker doesn't understand negation either.** A cross-encoder reads query and book together and should, in principle, see the "not"; MiniLM (trained on web search) does not, and makes ranking quality worse (0.28 vs 0.31).
3. **Stripping alone only gets back to the base rate**, by construction: the ruled-out thing was common to begin with.
4. **Tag filters do the real work**: hybrid with stripping and a hard filter goes from 62% to 30% violations and from 0.31 to 0.50 NDCG.
5. **Shelfwise gets there without being told.** Its parser reads "without the romance" as an exclusion on the romance tag (and "less violent", "not for kids", "nothing supernatural" likewise), so the request as typed already lands at 31% violations, with the best ranking quality of any condition. An extra hard filter adds little (28%), as expected: the parser already applied one.

Soft filters (move flagged books down 10 places) sit between off and hard everywhere, e.g. hybrid stripped 51% → 45% (soft) → 30% (hard).

### By tag

Why do ~30% violations survive a hard filter? Because the filter can only be as good as the tags it trusts:

| Tag | Hybrid, as typed | Hybrid, stripped + hard | Shelfwise, as typed | Tagger vs labels: κ |
| --- | --- | --- | --- | --- |
| supernatural | 86% | **9%** | 28% (13% + hard) | 0.88 |
| audience | 78% | **18%** | 16% | 0.90 |
| romance | 59% | 30% | 23% | 0.73 (quadratic) |
| pace | 40% | 30% | 30% | 0.31 (quadratic) |
| darkness | 51% | 37% | 37% | 0.53 (quadratic) |
| violence | 59% | 49% | 46% | 0.66 (quadratic) |

(Pairs per tag: 5–7, so each cell is noisy; the pattern across tags is the finding.) Where the tagger and the labels agree on the category (supernatural yes/no, audience), filtering removes nearly all violations. On graded scales they agree on the *direction* (quadratic κ 0.5–0.7) but often not on the exact level: a book one labeller calls violence 3 ("graphic") and the tagger calls 2 passes a `violence>=3` filter. Pace is the weakest: κ 0.31, and "slow" is a matter of taste.

### Lure pairs (3)

When the ruled-out thing is rare in the base results ("a mystery in a small English village" / "… no ghosts or psychics"), naming it drags it in:

| System | Base request | Negated, as typed |
| --- | --- | --- |
| BM25 | 13% | 30% |
| Dense | 18% | 28% |
| Hybrid | 17% | 42% |
| Hybrid + MiniLM rerank | 24% | 52% |
| **Shelfwise** | 21% | **7%** |

Three pairs only, so read the direction, not the numbers: hybrid more than doubles the violations it would have had if the reader hadn't mentioned ghosts at all, and the reranker is the worst. Shelfwise goes the other way.

### What the hard filter costs

Of the 209 books graded relevant (2–3) for the negated requests, the hard filter removes 10 (4.8%). By the labels, 8 of those do break the negation, so removing them is right (the relevance grade and the tag label disagree about them) and 2 don't: those are tagger mistakes, a real recall cost of about 1%.

## What it means for the product

- Negation is a **parsing** problem, not a ranking problem. No amount of embedding or off-the-shelf reranking fixes "without": the query has to be understood and turned into a constraint.
- Hard filters are safe for categorical tags with a reliable tagger (supernatural, audience), and should stay soft or carry an "approximately" for graded ones (violence, darkness, pace), where a one-step tagging disagreement decides the outcome.

## Limitations

- **The violation labels are Claude's**, an LLM's, not a person's. They were made without looking at the tagger's output, from the record and general knowledge of the books, by the written rules; but a model judging a model is weaker evidence than human labels. A person graded a blind sample of 60 of them (10 per tag, spread over Claude's answers, Claude's answers hidden; `eval/reports/20261010-235923_95bd6ab-dirty_violation-agreement.json`):

  | Tag | Same answer | κ | Same violation decision |
  | --- | --- | --- | --- |
  | supernatural | 10/10 | 1.00 | 100% |
  | romance | 9/10 | 0.95 (quadratic) | 95% |
  | audience | 9/10 | 0.85 | 95% |
  | darkness | 6/10 | 0.83 (quadratic) | 90% |
  | violence | 7/10 | 0.58 (quadratic) | 80% |
  | pace | 5/10 | 0.62 (quadratic) | 80% |

  The same split as between the tagger and the labels: categorical tags agree, graded ones differ by a step (13 of the 14 disagreements are one step apart). So the violation rates for supernatural, romance and audience pairs are trustworthy; for violence and pace, read them as ±1 level. Ten questions per tag is a small sample.
- **Small:** 37 removal pairs, 3 lure pairs, 5–7 pairs per tag. Differences under ~10 points between conditions are within the noise.
- **Perfect stripping:** "stripped" is the base request itself. A real negation remover would do no better and could do worse.
- **Drafted queries:** the pairs were drafted (by Claude) and reviewed by a person, not collected from real readers.
- **One catalog, one tagger, one embedder.** Shelfwise's result depends on its parser (Qwen3-4B, answers cached); the numbers are for that configuration.

## Reproduce

```bash
make label-violations JUDGE=<initials>          # or use the committed Claude labels
uv run python scripts/negation_study.py --judge claude \
  --systems bm25 dense hybrid hybrid_rerank parsed_hybrid --reranker minilm --parser cascade
```

Needs the catalog, the LLM tags (`make tag`), the pooled and graded pairs (`make pool`), and the parser's cached answers (committed in `eval/data/llm_cache.jsonl`).
