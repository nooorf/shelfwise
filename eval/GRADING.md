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
| similarity ("like X") | X itself: **0** (they've read it). Shares what makes X appealing: **3** or **2** |
| learning (course / technical) | Weigh topic **and** level **and** goal. A beginner asking, and an advanced reference: **1**. The right level and topic: **3** |
| vague ("something good", "surprise me") | A well-liked book most readers would enjoy: **2**. Otherwise: **1**. Rarely 3 |
| adversarial | A request for a book that doesn't exist: every book **0**, except the real book it refers to: **1**. Contradictory or injection queries: **0** unless a book genuinely matches the sensible part |

## Process

- Grades are made with `scripts/label.py`, one book at a time, without seeing which system retrieved it or its rank.
- Title, genres and the opening of the description are usually enough. If unsure between two grades, pick the lower one.
- Each grade records the grader's initials (`judge` column). A second grader grades a sample blind to measure agreement, which bounds how precise any metric can be.

## Pre-labels and review

An LLM (Claude) can pre-grade pooled pairs by these same rules, with a one-line reason where the grade isn't obvious. Pre-labels live in `data/prelabels.csv` and are **not** judgments: they count only after a person reviews them: `make grades-doc` writes every query with its books and suggested grades to one Markdown document, the reviewer corrects grades in place, and `make import-grades` saves the reviewed document. Reviewed grades record the judge as `<initials>-review`, so they can always be separated from independent grades.

Reviewing is faster than grading but anchors the reviewer on the suggestion, so agreement is measured on pairs graded **independently** by both:

| Pairs | Categories | Exact agreement | Weighted κ | Relevant / not κ |
| --- | --- | --- | --- | --- |
| 201 (2026-10-07) | author, lookup only | 98.5% | 0.98 | 0.97 |

The independent overlap so far covers only near-mechanical categories; a sample of the subjective ones (vague, discovery, negation, similarity) still needs independent human grades before the pre-label agreement can be quoted for them.
