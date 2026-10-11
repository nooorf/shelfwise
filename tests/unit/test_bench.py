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


def test_the_newest_voice_report(tmp_path: Path) -> None:
    spread = {"n": 3, "mean": 1200.0, "p50": 1100.0, "p95": 1500.0}
    condition = {
        "questions": 3, "answered": 3, "ttfa": spread,
        "stages": {"endpoint": 700.0, "transcribe": 300.0, "parse": 100.0, "retrieve": 50.0,
                   "voice": 30.0, "playback": 15.0, "handoffs": 5.0},
        "first_note": None, "av_offset": None, "fps": None, "fps_p5": None,
    }  # fmt: skip

    def report(created: str) -> dict:
        return {
            "created": created, "git": "abc", "kind": "voice", "questions": ["a", "b", "c"],
            "parser": "cascade", "browser": "Chromium 140", "machine": "Apple M2, 8 GB",
            "avatar_model": "sample.vrm",
            "conditions": {"off": condition,
                           "on": condition | {"av_offset": spread | {"abs_p95": 40.0},
                                              "fps": spread, "fps_p5": 55.0}},
            "avatar_cost_ms": spread | {"ci95": [-900.0, 1100.0]}, "avatar_load": {"first_frame_ms": spread, "model_ms": None},
            "rows": {"off": [], "on": []},
        }  # fmt: skip

    (tmp_path / "1_abc_voice.json").write_text(json.dumps(report("2026-10-10T00:00:00")))
    (tmp_path / "2_abc_voice.json").write_text(json.dumps(report("2026-10-11T00:00:00")))

    voice = load_bench(tmp_path).voice

    assert voice is not None and voice.file == "2_abc_voice.json" and voice.questions == 3
    assert voice.off.stages is not None and next(iter(voice.off.stages)) == "endpoint"
    assert voice.on.av_offset is not None and voice.on.av_offset.abs_p95 == 40.0
    assert voice.off.av_offset is None and voice.avatar_load.model_ms is None
    assert voice.avatar_cost_ms is not None and voice.avatar_cost_ms.ci95 == (-900.0, 1100.0)
