"""Lexical retrieval: BM25 per field, held in memory (design doc §13).

Title, author and body (description + genres + tags) are separate BM25 indexes so a title match
can count for more than a passing mention in a description. Scores come back for *every* work as
an array aligned with `work_ids`, so hard filters can be applied as a mask before ranking.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import bm25s
import numpy as np
import Stemmer
from sqlalchemy import Connection, text

from shelfwise.ingest.normalize import fold_text

# Starting weights, not tuned values: the eval runner grid-searches them on the dev split (§14.1).
DEFAULT_FIELD_WEIGHTS: Mapping[str, float] = {"title": 2.0, "author": 1.5, "body": 1.0}
FIELDS = ("title", "author", "body")
# Words that carry no meaning in a library request; removed from queries only, so titles like
# "The Book Thief" stay findable by their full title.
QUERY_FILLER = frozenset(
    {
        "book", "books", "novel", "novels", "something", "anything", "want", "need", "looking",
        "read", "reading", "recommend", "please", "good", "great", "story", "stories",
    }
)  # fmt: skip


@dataclass(frozen=True)
class LexicalDoc:
    work_id: int
    title: str
    author: str
    body: str


@dataclass(frozen=True)
class LexicalHit:
    work_id: int
    score: float


class LexicalIndex:
    def __init__(
        self, docs: list[LexicalDoc], weights: Mapping[str, float] = DEFAULT_FIELD_WEIGHTS
    ) -> None:
        self.work_ids = np.array([d.work_id for d in docs], dtype=np.int64)
        self.weights = dict(weights)
        self._stemmer = Stemmer.Stemmer("english")
        self._indexes: dict[str, bm25s.BM25 | None] = {
            field: self._build([getattr(d, field) for d in docs]) for field in FIELDS
        }

    def __len__(self) -> int:
        return len(self.work_ids)

    def _tokenize(self, texts: list[str]) -> list[list[str]]:
        return bm25s.tokenize(  # type: ignore[return-value]
            [fold_text(t) for t in texts],
            stopwords="en",
            stemmer=self._stemmer,
            return_ids=False,
            show_progress=False,
        )

    def _build(self, texts: list[str]) -> bm25s.BM25 | None:
        tokens = self._tokenize(texts)
        if not any(tokens):
            return None
        index = bm25s.BM25()
        index.index(tokens, show_progress=False)
        return index

    def field_scores(self, query: str) -> dict[str, np.ndarray]:
        """Raw BM25 score per field for every work (zeros when nothing matches)."""
        content = " ".join(w for w in fold_text(query).split() if w not in QUERY_FILLER)
        tokens = self._tokenize([content])[0]
        zeros = np.zeros(len(self), dtype=np.float32)
        return {
            field: (index.get_scores(tokens) if index is not None and tokens else zeros)
            for field, index in self._indexes.items()
        }

    def scores(self, query: str) -> np.ndarray:
        fields = self.field_scores(query)
        return sum((self.weights[f] * fields[f] for f in FIELDS), np.zeros(len(self)))

    def search(
        self, query: str, k: int = 10, allowed: np.ndarray | None = None
    ) -> list[LexicalHit]:
        """Top-k works with a positive score; `allowed` is a boolean mask over `work_ids`."""
        scores = self.scores(query)
        if allowed is not None:
            scores = np.where(allowed, scores, 0.0)
        top = np.argsort(-scores, kind="stable")[:k]
        return [LexicalHit(int(self.work_ids[i]), float(scores[i])) for i in top if scores[i] > 0]


_DOCS_SQL = text(
    """
    SELECT w.work_id,
           concat_ws(' ', w.title, w.subtitle) AS title,
           coalesce(
               (SELECT string_agg(a.display, ' ' ORDER BY wa.position)
                  FROM work_author wa JOIN author a USING (author_id)
                 WHERE wa.work_id = w.work_id), ''
           ) AS author,
           concat_ws(' ', w.description, array_to_string(w.genres, ' '),
                     array_to_string(w.tags, ' ')) AS body
    FROM work w
    ORDER BY w.work_id
    """
)


def build_lexical_index(
    conn: Connection, weights: Mapping[str, float] = DEFAULT_FIELD_WEIGHTS
) -> LexicalIndex:
    docs = [LexicalDoc(r.work_id, r.title, r.author, r.body) for r in conn.execute(_DOCS_SQL)]
    return LexicalIndex(docs, weights)
