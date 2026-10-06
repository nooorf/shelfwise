"""Embedding models under comparison (design doc §11.4). Final choice comes from the benchmark."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingModel:
    name: str  # short key stored in work_embedding.model_name
    hf_id: str
    query_prefix: str = ""  # some models expect queries phrased differently from documents
    max_seq_length: int = 512  # longer adds memory and time for little gain on book blurbs


MODELS: dict[str, EmbeddingModel] = {
    m.name: m
    for m in (
        # Weak baseline: small, fast, English only.
        EmbeddingModel("minilm", "sentence-transformers/all-MiniLM-L6-v2", max_seq_length=256),
        # Fast baseline. BGE's documented instruction for short queries against passages.
        EmbeddingModel(
            "bge-base",
            "BAAI/bge-base-en-v1.5",
            query_prefix="Represent this sentence for searching relevant passages: ",
        ),
        # Primary candidate: instruction-aware; the task description is ours to write.
        EmbeddingModel(
            "qwen3-0.6b",
            "Qwen/Qwen3-Embedding-0.6B",
            query_prefix=(
                "Instruct: Given a reader's request to a library, retrieve books that match it\n"
                "Query: "
            ),
        ),
    )
}
