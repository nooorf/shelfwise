# Grading guidelines

How relevance judgments in `data/qrels.csv` are made. Every grade in the benchmark follows these rules, so results can be reproduced and checked.

## The question

For each (query, book) pair: **would this person be happy if a librarian handed them this book?**

| Grade | Meaning | Example: "something dark and psychological with a twist" |
| --- | --- | --- |
| **3** | Exactly what they asked for; you'd hand it over | *The Silent Patient* |
| **2** | Clearly fits, with a small mismatch | A dark thriller without much of a twist |
| **1** | Partly related: right genre but wrong mood, or right topic but wrong level | A light, cozy mystery |
| **0** | Not what they asked for | A cookbook |

A book counts as **relevant** in the metrics at grade 2 or 3.

## What to judge, and what to ignore

- **Ignore** availability and exact numeric limits ("under 300 pages", "after 2015"). The system enforces those separately, and their correctness is tested by code, not by graders.
- **Do judge** vague wishes: "short", "dark", "for beginners", "not too violent", "cozy".
- Judge the book, not the edition: any edition of the right book gets the same grade.

## Rules by query category

| Category | How to grade |
| --- | --- |
| lookup ("do you have X") | The requested book in any edition: **3**. An adaptation of it (graphic novel, abridged): **2**. Same author or same series: **1**. Anything else: **0** |
| author | Books by that author: **3**. If the query excludes one ("other than 1984"), that book is **0** |
| negation ("nothing supernatural", "no romance", "not for kids") | Grade the whole request, negation included. A book that clearly has what was ruled out: **0**, however well it fits the rest. A minor or late element of it ("a supernatural reveal" in the last chapter): at most **1**. "Not too X" allows a little X |
| similarity ("like X") | X itself: **0** (they've read it). Shares what makes X appealing: **3** or **2** |
| learning (course / technical) | Weigh topic **and** level **and** goal. A beginner asking, and an advanced reference: **1**. The right level and topic: **3** |
| vague ("something good", "surprise me") | A well-liked book most readers would enjoy: **2**. Otherwise: **1**. Rarely 3 |
| adversarial | A request for a book that doesn't exist: every book **0**, except the real book it refers to: **1**. Contradictory or injection queries: **0** unless a book genuinely matches the sensible part |

## Process

- Grades are made with `scripts/label.py`, one book at a time, without seeing which system retrieved it or its rank.
- Title, genres and the opening of the description are usually enough. If unsure between two grades, pick the lower one.
- Each grade records the grader's initials (`judge` column). A second grader grades a sample blind to measure agreement, which bounds how precise any metric can be.

## Pre-labels and review

An LLM (Claude) can pre-grade pooled pairs by these same rules, with a one-line reason where the grade isn't obvious. Pre-labels live in `data/prelabels.csv` and are **not** judgments: they count only after a person reviews them: `make grades-doc` writes every query with its books and suggested grades to one Markdown document, the reviewer corrects grades in place, and `make import-grades` saves the reviewed document. Reviewed grades record the judge as `<initials>-review`, so they can always be separated from independent grades. Only rows the reviewer changed or ticked as checked (`2 ✓`) get their initials; rows nobody but Claude looked at are saved as `claude-review` (since round 2, 2026-10-08, when Claude did the review pass and the reviewer decided only the open calls).

Reviewing is faster than grading but anchors the reviewer on the suggestion, so agreement is measured on pairs graded **independently** by both:

| Pairs | Categories | Exact agreement | Weighted κ | Relevant / not κ |
| --- | --- | --- | --- | --- |
| 201 (2026-10-07) | author, lookup only | 98.5% | 0.98 | 0.97 |

**First review (2026-10-07):** the reviewer changed 14 of 1,920 suggestions (0.7%): 11 in one adversarial query, where the suggestions had broken the rule above for nonexistent books, plus 3 judgement calls. The review also surfaced 14 transcription errors in the suggestions themselves (grades shifted by one row within 3 queries, e.g. a romance novel graded 3 for "horror novels"); those were fixed in `prelabels.csv` before import. A low change rate after review is not evidence of accuracy on its own: anchoring makes reviewers accept suggestions.

The independent overlap so far covers only near-mechanical categories; a sample of the subjective ones (vague, discovery, negation, similarity) still needs independent human grades before the pre-label agreement can be quoted for them.

## From round 2: Claude's grades, checked on a blind sample

Reviewing thousands of pairs by hand isn't realistic, and a review anchored on the suggestions would overstate how much a person checked. From round 2 (2026-10-08), the pooled pairs are graded by Claude (after its own review pass, judge `claude-review`), and a person decides only the rule-level calls. How far those grades can be trusted is measured instead on a **blind sample**: `eval/data/blind_sample.csv`, 160 pairs drawn at random from the Claude-graded pairs (40 for each suggested grade, at most 2 per query, author and lookup queries left out, pairs the reviewer had already seen excluded). The person grades them with the usual labelling tool, which never shows Claude's grade (`make label-blind JUDGE=NF`), then `make agreement JUDGE=NF` reports exact agreement, quadratic-weighted κ, relevant/not κ, the confusion matrix and agreement per category. Those numbers go in the table above.

The sample is stratified by Claude's grade, so every grade is measured; because grade 0 dominates the pool, raw agreement on the whole pool would be higher than on the sample. Any later pool growth is graded by Claude the same way and doesn't need a new review round; a new blind sample is drawn only if the rules or the grader change.
