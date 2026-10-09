import json
from pathlib import Path

from shelfwise.evaluation.bench import load_bench


def metric(mean: float) -> dict:
    return {"mean": mean, "ci95": [mean - 0.05, mean + 0.05]}


def retrieval(created: str, split: str, systems: dict[str, float]) -> dict:
    return {
        "created": created, "git": "abc", "split": split, "queries_scored": 3,
        "embedding_model": "bge-base", "parser": "cascade",
        "systems": {
            name: {
                "overall": {"ndcg@10": metric(score), "recall@10": metric(0.5),
                            "mrr": metric(0.4), "judged@10": metric(1.0)},
                "ndcg@10_by_category": {"vague": score},
                "per_query": {},
                **({"latency_ms": {"p50": 10.0, "p95": 20.0}} if name == "dense" else {}),
            }
            for name, score in systems.items()
        },
    }  # fmt: skip


def parser(created: str, split: str) -> dict:
    strict = {"precision": 0.9, "recall": 0.8, "f1": 0.85}
    return {"created": created, "git": "abc", "split": split, "parser": "cascade",
            "llm": {"model": "qwen3:4b"},
            "summary": {"n": 5, "intent_accuracy": 0.9, "exact_match": 0.7,
                        "constraints_strict": strict}}  # fmt: skip


def test_the_newest_dev_reports_best_system_first(tmp_path: Path) -> None:
    files = {
        "old.json": retrieval("2026-10-01T00:00:00", "dev", {"bm25": 0.9}),
        "new.json": retrieval("2026-10-02T00:00:00", "dev", {"bm25": 0.4, "dense": 0.6}),
        "test.json": retrieval("2026-10-03T00:00:00", "test", {"bm25": 1.0}),
        "parser-dev.json": parser("2026-10-01T00:00:00", "dev"),
        "parser-all.json": parser("2026-10-04T00:00:00", "all"),  # contains test queries
        "tags.json": {"created": "2026-10-05T00:00:00", "per_tag": {}},
    }
    for name, report in files.items():
        (tmp_path / name).write_text(json.dumps(report))
    (tmp_path / "broken.json").write_text("{")

    bench = load_bench(tmp_path)

    assert bench.retrieval is not None and bench.retrieval.file == "new.json"
    assert [s.name for s in bench.retrieval.systems] == ["dense", "bm25"]
    assert bench.retrieval.systems[0].latency_ms == {"p50": 10.0, "p95": 20.0}
    assert bench.retrieval.systems[1].latency_ms is None
    assert bench.parser is not None and bench.parser.file == "parser-dev.json"
    assert bench.parser.constraint_f1 == 0.85


def test_no_reports_is_an_empty_bench(tmp_path: Path) -> None:
    bench = load_bench(tmp_path)
    assert bench.retrieval is None and bench.parser is None


def test_the_newest_grounding_report_in_a_fixed_system_order(tmp_path: Path) -> None:
    rates = {"n": 10, "invented": 0.0, "availability": 0.1, "claim": 0.0, "number": 0.0}
    report = {
        "created": "2026-10-10T00:00:00", "git": "abc", "llm": "qwen3:4b", "cases": 10,
        "summary": {
            "full": {"overall": {**rates, "raw_invented": 0.2}},
            "llm_only": {"overall": {**rates, "unowned_share": 0.75},
                         "nonexistent": {**rates, "affirmed": 0.5}},
        },
    }  # fmt: skip
    (tmp_path / "x_grounding.json").write_text(json.dumps(report))

    grounding = load_bench(tmp_path).grounding

    assert grounding is not None and [s.name for s in grounding.systems] == ["llm_only", "full"]
    assert grounding.systems[0].unowned == 0.75 and grounding.systems[0].affirmed == 0.5
    assert grounding.systems[1].raw_invented == 0.2
