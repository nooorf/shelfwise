"""Dense retrieval: exact dot-product search over an in-memory matrix.

At library scale (tens of thousands of works) exact search takes milliseconds and has perfect
recall; approximate indexes would add a filtered-search recall problem for no benefit. The matrix
is aligned to a given work-id order (the lexical index's), so one filter mask serves both.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import Connection, select

from shelfwise.catalog import schema


@dataclass(frozen=True)
class DenseHit:
    work_id: int
    score: float


class DenseIndex:
    def __init__(self, work_ids: np.ndarray, matrix: np.ndarray, model_name: str) -> None:
        if matrix.shape[0] != len(work_ids):
            raise ValueError("matrix rows must match work_ids")
        self.work_ids = work_ids
        self.matrix = matrix.astype(np.float32, copy=False)
        self.model_name = model_name
        # Works without an embedding get a zero row: they score 0 and never rank.
        self.has_vector = np.linalg.norm(self.matrix, axis=1) > 0

    @classmethod
    def load(cls, conn: Connection, model_name: str, work_ids: np.ndarray) -> "DenseIndex":
        we = schema.work_embedding  # typed select, so pgvector decodes vectors
        rows = conn.execute(
            select(we.c.work_id, we.c.embedding).where(we.c.model_name == model_name)
        ).all()
        if not rows:
            raise LookupError(
                f"no embeddings stored for model {model_name!r}; run scripts/embed.py"
            )
        vectors = {r.work_id: np.asarray(r.embedding, dtype=np.float32) for r in rows}
        dim = len(next(iter(vectors.values())))
        matrix = np.zeros((len(work_ids), dim), dtype=np.float32)
        for row, work_id in enumerate(work_ids.tolist()):
            if work_id in vectors:
                matrix[row] = vectors[work_id]
        return cls(work_ids, matrix, model_name)

    def scores(self, query_vector: np.ndarray) -> np.ndarray:
        return self.matrix @ query_vector.astype(np.float32, copy=False)

    def search(
        self,
        query_vector: np.ndarray,
        k: int = 10,
        allowed: np.ndarray | None = None,
        max_gap: float | None = None,
        ignore: Sequence[int] = (),
    ) -> list[DenseHit]:
        """Top-k works by similarity among `allowed`. With `max_gap`, a work scoring more than
        that below the best match in the whole catalog is left out, so filters that leave only
        off-topic books return nothing instead of them. `ignore` keeps works out of that best
        match (a "like X" search's seed book, which matches itself perfectly)."""
        raw = self.scores(query_vector)
        ok = self.has_vector if allowed is None else (self.has_vector & allowed)
        if max_gap is not None:
            reference = self.has_vector & ~np.isin(self.work_ids, list(ignore))
            if reference.any():
                ok = ok & (raw >= float(raw[reference].max()) - max_gap)
        scores = np.where(ok, raw, -np.inf)
        top = np.argsort(-scores, kind="stable")[:k]
        return [DenseHit(int(self.work_ids[i]), float(scores[i])) for i in top if ok[i]]
