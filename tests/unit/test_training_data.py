from collections import Counter
from pathlib import Path

from shelfwise.evaluation.judgments import Judgment
from shelfwise.evaluation.queries import Query
from shelfwise.evaluation.splits import split_of
from shelfwise.tagging.facets import BookRecord
from shelfwise.training.data import (
    ScoredPair,
    SyntheticRequest,
    Triplet,
    dev_queries,
    fold_of,
    graded_examples,
    load_synthetic,
    mine_negatives,
    reuses_record,
    synthetic_examples,
    write_jsonl,
)
from shelfwise.training.synthetic import SyntheticOutput, build_messages, clean


def test_fold_is_deterministic_and_about_a_quarter_val():
    families = [f"F{i}" for i in range(2000)]
    folds = Counter(fold_of(f) for f in families)
    assert 0.2 < folds["val"] / len(families) < 0.3
    assert [fold_of(f) for f in families] == [fold_of(f) for f in families]


def test_fold_does_not_follow_the_dev_test_split():
    dev = [f"F{i}" for i in range(2000) if split_of(f"F{i}") == "dev"]
    share = sum(fold_of(f) == "val" for f in dev) / len(dev)
    assert 0.2 < share < 0.3


def test_reuses_record_names_the_title():
    why = reuses_record("anything like the hunger games but softer", "The Hunger Games", [], None)
    assert why == "names the title"


def test_reuses_record_ignores_subtitle_and_short_titles():
    assert reuses_record("a book about it all", "It", ["Stephen King"], None) is None
    assert (
        reuses_record(
            "a long family saga", "Sarum: The Novel of England", ["Edward Rutherfurd"], None
        )
        is None
    )
    assert reuses_record("i want sarum", "Sarum: The Novel of England", [], None)


def test_reuses_record_names_the_author_by_surname():
    assert reuses_record("something like rowling wrote", "X Y", ["J. K. Rowling"], None)
    assert reuses_record("a short read", "X Y", ["Al"], None) is None  # 2-letter names ignored


def test_reuses_record_copies_the_description():
    blurb = "A young girl falls through a rabbit hole into a fantasy world."
    assert reuses_record("girl falls through a rabbit hole", "Alice", [], blurb)
    assert reuses_record("girl in a strange fantasy world", "Alice", [], blurb) is None


def _q(qid: str, family: str, text: str = "q") -> Query:
    return Query(qid, "genre", "student", family, "llm-draft", text)


def test_dev_queries_keep_one_fold_of_dev_only():
    families = [f"F{i}" for i in range(400)]
    queries = [_q(f"Q{i}", f) for i, f in enumerate(families)]
    train, val = dev_queries(queries, "train"), dev_queries(queries, "val")
    assert not {q.id for q in train} & {q.id for q in val}
    assert all(split_of(q.family) == "dev" for q in train + val)
    assert all(fold_of(q.family) == "val" for q in val)


def test_graded_examples_soft_labels_and_triplets():
    q = _q("G1", "F", "cozy mystery")
    texts = {"a": "A", "b": "B", "c": "C", "d": "D"}
    judgments = [
        Judgment("G1", "a", 3),
        Judgment("G1", "b", 2),
        Judgment("G1", "c", 1),
        Judgment("G1", "d", 0),
        Judgment("G1", "x", 3),  # no text: skipped
        Judgment("G1", "a", None),  # ungraded: skipped
    ]
    triplets, pairs = graded_examples([q], judgments, texts)
    assert sorted(p.label for p in pairs) == [0.0, 1 / 3, 2 / 3, 1.0]
    assert sorted(t.positive for t in triplets) == ["A", "B"]
    assert {t.negative for t in triplets} == {"D"}
    assert all(t.anchor == "cozy mystery" for t in triplets)


def test_graded_examples_without_negatives_make_no_triplets():
    triplets, pairs = graded_examples([_q("G1", "F")], [Judgment("G1", "a", 3)], {"a": "A"})
    assert triplets == [] and len(pairs) == 1


def test_mine_negatives_skips_top_and_same_author():
    ranked = ["p", "t1", "t2", "s", "n1", "n2", "n3", "n4"]
    authors = {"p": frozenset({1}), "s": frozenset({1, 2}), "n1": frozenset({3})}
    assert mine_negatives(ranked, "p", authors, skip=3, count=2) == ["n1", "n2"]


def _req(key: str, text: str, rejected: str = "") -> SyntheticRequest:
    return SyntheticRequest(key, text, "mood", "m", "v", rejected)


def test_synthetic_examples_drop_rejected_and_missing_books():
    texts = {"a": "A", "n": "N"}
    reqs = [_req("a", "sad and slow"), _req("a", "names it", "names the title"), _req("z", "x")]
    triplets, pairs = synthetic_examples(reqs, texts, {"sad and slow": ["n", "gone"]})
    assert triplets == [Triplet("sad and slow", "A", "N")]
    assert pairs == [ScoredPair("sad and slow", "A", 1.0), ScoredPair("sad and slow", "N", 0.0)]


def test_jsonl_round_trip(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    rows = [_req("a", "x"), _req("b", "y", "names the author")]
    write_jsonl(path, [Triplet("q", "p", "n")])
    assert path.read_text().count("\n") == 1
    import dataclasses
    import json

    path.write_text("".join(json.dumps(dataclasses.asdict(r)) + "\n" for r in rows))
    assert load_synthetic(path) == rows
    assert load_synthetic(tmp_path / "missing.jsonl") == []


def test_prompt_shows_the_record_and_schema_validates():
    book = BookRecord(
        1, "Dune", ["Frank Herbert"], ["science fiction"], ["classics"], "Sand.", 1965
    )
    messages = build_messages(book, ["ecology"])
    assert "Title: Dune" in messages[1]["content"]
    assert "Themes: ecology" in messages[1]["content"]
    out = SyntheticOutput.model_validate(
        {"mood": "something epic and strange", "specific": "politics on a desert planet please"}
    )
    assert out.mood
    assert clean('  "a slow, sad book"  ') == "a slow, sad book"


def test_fine_tuned_models_are_unavailable_until_trained(tmp_path: Path, monkeypatch):
    import pytest

    from shelfwise.embed.encoder import load_embedder
    from shelfwise.embed.models import MODELS
    from shelfwise.ranking.rerank import MODELS as RERANKERS
    from shelfwise.ranking.rerank import load_reranker

    monkeypatch.chdir(tmp_path)  # no models/ here
    assert MODELS["bge-base"].available
    assert not MODELS["bge-base-ft"].available
    assert not RERANKERS["bge-base-ft"].available
    with pytest.raises(LookupError, match="isn't trained yet"):
        load_embedder("bge-base-ft")
    with pytest.raises(LookupError, match="isn't trained yet"):
        load_reranker("minilm-ft")
    (tmp_path / "models" / "bge-base-ft").mkdir(parents=True)
    assert MODELS["bge-base-ft"].available


def test_guard_sees_whether_weights_moved():
    import torch

    from shelfwise.training.guard import max_change, snapshot

    top = torch.nn.Linear(3, 1)
    model = torch.nn.Sequential(torch.nn.Linear(3, 3), top)
    before = snapshot(model)
    assert max_change(model, before) == 0
    with torch.no_grad():
        top.bias.add_(0.5)
    assert abs(max_change(model, before) - 0.5) < 1e-6
