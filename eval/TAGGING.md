# Tagging guidelines

How the human book tags in `data/facet_labels.csv` are made. The LLM tagger is scored against these labels (`make score-tags`), so the rules match its rubric in `src/shelfwise/tagging/facets.py`.

## The question

For each book: **what would a reader who has finished it say?** Use the record shown (genres, subjects, description) and anything you know about the book. Never look at the LLM's tags first.

## Tags

| Tag | Values | Notes |
| --- | --- | --- |
| fiction | fiction / nonfiction | Graphic novels and short-story collections are fiction; memoirs are nonfiction |
| audience | children (under ~12) / ya (teenage) / adult | Who it's written for, not who could read it |
| darkness | 0 light · 1 some serious moments · 2 dark · 3 very dark | 2: crime, abuse, grief or violence are central. 3: bleak, disturbing, horror |
| romance | 0 none · 1 minor subplot · 2 significant subplot · 3 the central story | Romance novels are 3 |
| violence | 0 none · 1 mild or off-page · 2 on-page · 3 graphic or gory | |
| pace | slow · medium · fast | Nonfiction is medium unless clearly otherwise |
| supernatural | yes · no · unclear | Magic, ghosts, vampires, curses, psychic powers. Science-fiction technology is **not** supernatural |
| historical setting | yes · no · unclear | Fiction only. Yes only if the period was already the past when the book was written: *A Tale of Two Cities* yes, *Pride and Prejudice* no. Add the period if you know it |
| reading level | intro · intermediate · advanced · none | Nonfiction only. Technical, academic or course books; none for general-audience nonfiction (memoir, popular history) |

## Process

- Labels are made with `scripts/label_tags.py`, one book at a time, in a fixed genre-balanced order.
- **"Can't tell" (`?`) is a real answer.** Use it when neither the record nor your memory settles it. It's left out of scoring, which is better than a guess that counts as truth.
- If unsure between two neighbouring values, pick the one the description supports, not the one the genre suggests.
- Each label records the labeller's initials. A second person labels the first 50 books blind; their agreement with the first labeller is the realistic ceiling for the LLM's scores.
