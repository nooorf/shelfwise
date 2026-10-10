"""Training data for the fine-tuned embedder and reranker.

Two sources of (request, book) examples:

- **Graded pairs** from the dev split's query families. Those families are split again into a
  train fold and a val fold (`fold_of`); val picks the checkpoint, so it never trains. The test
  split is never read here: it is scored once per final configuration, at the end.
- **Synthetic requests** the LLM wrote for each book (synthetic.py), the book as the positive.
  They give every book in the catalog a few requests; real queries alone cover a few hundred.

Negatives: for graded queries, books a person or Claude judged 0. They are hard by
construction, because the pool is what the search systems returned. For synthetic requests,
books the base model ranks near the top but not first, by another author (`mine_negatives`):
probably wrong, possibly a book that fits as well (a false negative). In-batch negatives do the
rest.

Books are keyed by `work_key` (lowest ISBN-13) like the judgments, so data built today still
lines up after a catalog rebuild.
"""

import hashlib
import json
import random
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from shelfwise.evaluation.judgments import Judgment
from shelfwise.evaluation.queries import Query
from shelfwise.evaluation.splits import split_of

Fold = Literal["train", "val"]

RELEVANT = 2  # grade 2 or 3 counts as relevant, as in the metrics
SPAN_WORDS = 5  # a request copying this many consecutive description words is a leak


def fold_of(family: str) -> Fold:
    """About a quarter of the dev families go to val. Deterministic, salted apart from
    `split_of`, so the fold doesn't correlate with the dev/test split."""
    bucket = int(hashlib.sha1(f"fold:{family}".encode()).hexdigest()[:8], 16) % 4
    return "val" if bucket == 0 else "train"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def reuses_record(
    request: str, title: str, authors: Sequence[str], description: str | None
) -> str | None:
    """Why a synthetic request gives its book away, or None. A request that names the title, an
    author or quotes the blurb teaches lookup by copying, not what readers actually ask for."""
    words = _words(request)
    main = re.split(r"[:(]", title)[0]
    main_words = [w for w in _words(main) if w not in {"the", "a", "an"}]
    distinctive = bool(main_words) and (len(main_words) > 1 or len(main_words[0]) >= 4)
    if distinctive and _contains(words, main_words):
        return "names the title"
    for author in authors:
        name = _words(author)
        if name and len(name[-1]) >= 3 and name[-1] in words:
            return "names the author"
    blurb = _words(description or "")
    for i in range(len(blurb) - SPAN_WORDS + 1):
        if _contains(words, blurb[i : i + SPAN_WORDS]):
            return "copies the description"
    return None


@dataclass(frozen=True)
class Triplet:
    """Embedder example: the request, a book that fits, one that doesn't."""

    anchor: str
    positive: str
    negative: str


@dataclass(frozen=True)
class ScoredPair:
    """Reranker example: grade / 3 for graded pairs, 1 or 0 for synthetic ones."""

    query: str
    document: str
    label: float


def dev_queries(queries: Iterable[Query], fold: Fold) -> list[Query]:
    return [q for q in queries if split_of(q.family) == "dev" and fold_of(q.family) == fold]


def graded_examples(
    queries: Sequence[Query],
    judgments: Iterable[Judgment],
    texts: Mapping[str, str],
    seed: int = 0,
) -> tuple[list[Triplet], list[ScoredPair]]:
    """Every graded pair of these queries as a reranker example, and each relevant book paired
    with a judged-0 book of the same query as an embedder triplet. `texts` maps work_key to the
    book's search text (keys already resolved through merges); books without text are skipped."""
    by_query: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for j in judgments:
        if j.grade is not None and j.work_key in texts:
            by_query[j.query_id].append((j.work_key, j.grade))
    rng = random.Random(seed)
    triplets: list[Triplet] = []
    pairs: list[ScoredPair] = []
    for q in queries:
        graded = sorted(by_query.get(q.id, []))
        pairs += [ScoredPair(q.text, texts[key], grade / 3) for key, grade in graded]
        positives = [key for key, grade in graded if grade >= RELEVANT]
        negatives = [key for key, grade in graded if grade == 0]
        if not negatives:
            continue
        rng.shuffle(negatives)
        for i, key in enumerate(positives):
            triplets.append(Triplet(q.text, texts[key], texts[negatives[i % len(negatives)]]))
    return triplets, pairs


@dataclass(frozen=True)
class SyntheticRequest:
    work_key: str
    text: str
    style: str  # which instruction it answered ("mood", "specific")
    model: str
    prompt_version: str
    rejected: str = ""  # why it was dropped (reuses_record), or empty


def load_synthetic(path: Path) -> list[SyntheticRequest]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [SyntheticRequest(**json.loads(line)) for line in f if line.strip()]


def mine_negatives(
    ranked: Sequence[str],
    positive: str,
    authors: Mapping[str, frozenset[int]],
    skip: int = 10,
    count: int = 3,
) -> list[str]:
    """Hard negatives for a synthetic request from the base model's ranking: skip the first
    `skip` books (the likeliest other good answers), then take books by none of the positive's
    authors (another volume of the same series would be a false negative)."""
    own = authors.get(positive, frozenset())
    picked = []
    for key in ranked[skip:]:
        if key != positive and not (authors.get(key, frozenset()) & own):
            picked.append(key)
            if len(picked) == count:
                break
    return picked


def synthetic_examples(
    requests: Iterable[SyntheticRequest],
    texts: Mapping[str, str],
    negatives: Mapping[str, Sequence[str]],
) -> tuple[list[Triplet], list[ScoredPair]]:
    """`negatives` maps a request's text to its mined negative work_keys."""
    triplets: list[Triplet] = []
    pairs: list[ScoredPair] = []
    for r in requests:
        if r.rejected or r.work_key not in texts:
            continue
        negs = [k for k in negatives.get(r.text, ()) if k in texts]
        pairs.append(ScoredPair(r.text, texts[r.work_key], 1.0))
        pairs += [ScoredPair(r.text, texts[k], 0.0) for k in negs]
        if negs:
            triplets.append(Triplet(r.text, texts[r.work_key], texts[negs[0]]))
    return triplets, pairs


def write_jsonl(path: Path, rows: Iterable[Triplet | ScoredPair]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            n += 1
    return n
