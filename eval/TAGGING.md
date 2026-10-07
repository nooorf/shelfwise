# Tagging guidelines

How the human book tags in `data/facet_labels.csv` are made. The LLM tagger is scored against these labels (`make score-tags`), so the rules match its rubric in `src/shelfwise/tagging/facets.py`.

## The question

For each book: **what would a reader who has finished it say?** Use the record shown (genres, subjects, description) and anything you know about the book. Never look at the LLM's tags first.

## Tags

| Tag | Values | Notes |
| --- | --- | --- |
| fiction | fiction / nonfiction | Graphic novels and short-story collections are fiction; memoirs are nonfiction. Poetry collections are nonfiction; a narrative poem that tells an invented story (*The Faerie Queene*) is fiction |
| audience | children (under ~12) / ya (teenage) / adult | Who it's written for, not who could read it |
| darkness | 0 light · 1 some serious moments · 2 dark · 3 very dark | 2: crime, abuse, grief or violence are central. 3: bleak, disturbing, horror |
| romance | 0 none · 1 minor subplot · 2 significant subplot · 3 the central story | Romance novels are 3 |
| violence | 0 none · 1 mild or off-page · 2 on-page · 3 graphic or gory | |
| pace | slow · medium · fast | Nonfiction is medium unless clearly otherwise |
| supernatural | yes · no · unclear | Magic, ghosts, vampires, curses, psychic powers. Science-fiction technology is **not** supernatural |
| historical setting | yes · no · unclear | Fiction only. Yes if the story is set at least ~20 years (a generation) before the book was written: *A Tale of Two Cities* yes, *Pride and Prejudice* no, *Darkness at Noon* (written 1940 about 1936–38) no. A collection whose tales include clearly past eras: yes. Add the period if you know it |
| reading level | intro · intermediate · advanced · none | Nonfiction only. Technical, academic or course books; none for general-audience nonfiction (memoir, popular history) |

**Why "historical" is relative to the author, not to today's reader.** Against today, almost every older book would be historical, so the tag would mostly repeat the publication year we already store and could no longer tell historical fiction apart from a period classic. "Set in what is the past for a reader today" can still be worked out at search time: historical setting yes, or published long enough ago.

## Process

- Labels are made with `scripts/label_tags.py`, one book at a time, in a fixed genre-balanced order.
- **"Can't tell" (`?`) is a real answer.** Use it when neither the record nor your memory settles it. It's left out of scoring, which is better than a guess that counts as truth.
- If unsure between two neighbouring values, pick the one the description supports, not the one the genre suggests.
- Each label records the labeller's initials. A second person labels the first 50 books blind; their agreement with the first labeller is the realistic ceiling for the LLM's scores.

## Pre-labels and review

Claude can suggest tags for the labelling sample, by these same rules, from each book's record and general knowledge of well-known books, without looking at the LLM tagger's output. Suggestions live in `data/facet_prelabels.csv` (with a note where a tag needed judgement) and are **not** labels: they count only after a person reviews them. `make tags-doc` writes all of them to `eval/tags_review.md`, the reviewer corrects values in place, and `make import-tags JUDGE=<initials>` saves every book as that person's label under the judge `<initials>-review`.

Reviewing anchors on the suggestions, so reviewed labels are kept apart from labels made from scratch with `make label-tags`, and agreement (with Claude or with the LLM tagger) is best quoted on books labelled independently. Note that Claude is itself an LLM: the tagger is then scored against labels that a human reviewed starting from another model's answers, not against blind human labels. A blind second labeller (`--judge XY` on the first 50 books) gives the honest ceiling.
