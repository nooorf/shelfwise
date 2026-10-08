import numpy as np
import pytest

from shelfwise.embed.models import MODELS
from shelfwise.embed.text_builder import build_search_text, content_hash
from shelfwise.retrieval.dense import DenseIndex
from shelfwise.retrieval.fusion import rrf

from ..fakes import FakeEmbedder


def test_search_text_template() -> None:
    text = build_search_text(
        "The Silent Patient",
        authors=["Alex Michaelides"],
        genres=["psychological thriller"],
        tags=["psychotherapy patients", "marriage"],
        description="Alicia Berenson shoots her husband and never speaks again.",
    )

    assert text.splitlines() == [
        "Title: The Silent Patient",
        "By: Alex Michaelides",
        "Genres: psychological thriller",
        "Subjects: psychotherapy patients; marriage",
        "About: Alicia Berenson shoots her husband and never speaks again.",
    ]


def test_search_text_skips_empty_fields_and_hash_tracks_content() -> None:
    bare = build_search_text("Dune")

    assert bare == "Title: Dune"
    assert content_hash(bare) == content_hash("Title: Dune")
    assert content_hash(bare) != content_hash(build_search_text("Dune", description="Spice."))


def test_model_registry_has_query_instructions_where_needed() -> None:
    assert MODELS["minilm"].query_prefix == ""
    assert MODELS["bge-base"].query_prefix.startswith("Represent this sentence")
    assert "Query: " in MODELS["qwen3-0.6b"].query_prefix


def test_rrf_by_hand() -> None:
    fused = dict(rrf([[1, 2, 3], [3, 1]], k=60))

    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2] == pytest.approx(1 / 62)


def test_rrf_rewards_agreement_and_breaks_ties_by_id() -> None:
    order = [doc for doc, _ in rrf([[5, 1, 2], [1, 5, 9]])]

    assert order[:2] == [1, 5]  # equal score, lower id first
    assert set(order) == {1, 2, 5, 9}


def test_rrf_weights() -> None:
    order = [doc for doc, _ in rrf([[1], [2]], weights=[1.0, 3.0])]

    assert order == [2, 1]
    with pytest.raises(ValueError):
        rrf([[1], [2]], weights=[1.0])


@pytest.fixture
def index() -> DenseIndex:
    embedder = FakeEmbedder()
    texts = ["dark psychological thriller", "cozy village mystery", "space opera adventure"]
    vectors = embedder.encode_documents(texts)
    matrix = np.vstack([vectors, np.zeros((1, embedder.dim), dtype=np.float32)])  # id 40: no vector
    return DenseIndex(np.array([10, 20, 30, 40]), matrix, "fake")


def test_dense_search_ranks_by_similarity(index: DenseIndex) -> None:
    query = FakeEmbedder().encode_query("a psychological thriller")

    assert index.search(query, k=2)[0].work_id == 10


def test_dense_search_respects_mask_and_skips_missing_vectors(index: DenseIndex) -> None:
    query = FakeEmbedder().encode_query("a psychological thriller")
    allowed = np.array([False, True, True, True])

    ids = [h.work_id for h in index.search(query, k=10, allowed=allowed)]

    assert 10 not in ids and 40 not in ids
    assert set(ids) == {20, 30}


def test_dense_index_rejects_misaligned_matrix() -> None:
    with pytest.raises(ValueError):
        DenseIndex(np.array([1, 2]), np.zeros((3, 4)), "fake")


def test_dense_search_max_gap_drops_books_far_below_the_best_match() -> None:
    matrix = np.array([[1.0, 0.0], [0.9, np.sqrt(1 - 0.81)], [0.0, 1.0]], dtype=np.float32)
    index = DenseIndex(np.array([1, 2, 3]), matrix, "fake")
    query = np.array([1.0, 0.0], dtype=np.float32)
    only_far = np.array([False, False, True])

    assert [h.work_id for h in index.search(query, max_gap=0.2)] == [1, 2]
    assert index.search(query, allowed=only_far, max_gap=0.2) == []  # off-topic, not shown
    assert [h.work_id for h in index.search(query, allowed=only_far)] == [3]  # no floor


def test_dense_search_max_gap_ignores_the_seed_as_best_match() -> None:
    matrix = np.array([[1.0, 0.0], [0.7, np.sqrt(1 - 0.49)]], dtype=np.float32)
    index = DenseIndex(np.array([1, 2]), matrix, "fake")
    seed = matrix[0]

    assert index.search(seed, max_gap=0.2, ignore=[]) == index.search(seed, k=1)
    assert [h.work_id for h in index.search(seed, max_gap=0.2, ignore=[1])] == [1, 2]
