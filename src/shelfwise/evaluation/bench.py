"""The `/bench` page's data (design doc §22.2): the newest retrieval and parser reports from
`eval/reports`, trimmed to what the dashboard draws (no per-query rows)."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from shelfwise.evaluation.reports import REPORTS

K = 10


class Interval(BaseModel):
    mean: float
    ci95: tuple[float, float]


class SystemScore(BaseModel):
    name: str
    ndcg: Interval  # nDCG@10
    recall: float  # recall@10
    mrr: float
    judged: float  # share of the top 10 that is graded
    by_category: dict[str, float]  # nDCG@10 per query category
    latency_ms: dict[str, float] | None  # p50 / p95; None in reports from before timing


class RetrievalReport(BaseModel):
    file: str
    created: str
    git: str
    split: str
    queries: int
    embedding_model: str | None
    parser: str | None
    systems: list[SystemScore]  # best nDCG@10 first


class ParserReport(BaseModel):
    file: str
    created: str
    git: str
    split: str
    parser: str
    model: str | None
    queries: int
    intent_accuracy: float
    exact_match: float
    constraint_precision: float
    constraint_recall: float
    constraint_f1: float


class Bench(BaseModel):
    retrieval: RetrievalReport | None
    parser: ParserReport | None


def _reports(folder: Path) -> list[tuple[Path, dict[str, Any]]]:
    found = []
    for path in folder.glob("*.json"):
        try:
            found.append((path, json.loads(path.read_text())))
        except (OSError, json.JSONDecodeError):
            continue  # a half-written or broken file is skipped, not fatal
    return sorted(found, key=lambda item: str(item[1].get("created", "")), reverse=True)


def _system(name: str, result: dict[str, Any]) -> SystemScore:
    o = result["overall"]
    ndcg = o[f"ndcg@{K}"]
    return SystemScore(
        name=name,
        ndcg=Interval(mean=ndcg["mean"], ci95=tuple(ndcg["ci95"])),
        recall=o[f"recall@{K}"]["mean"],
        mrr=o["mrr"]["mean"],
        judged=o[f"judged@{K}"]["mean"],
        by_category=result[f"ndcg@{K}_by_category"],
        latency_ms=result.get("latency_ms"),
    )


def load_bench(folder: Path = REPORTS, split: str = "dev") -> Bench:
    """The newest retrieval and parser reports on `split`: the locked test split (and "all",
    which contains it) is never shown here."""
    retrieval = parser = None
    for path, report in _reports(folder):
        if retrieval is None and "systems" in report and report.get("split") == split:
            systems = [_system(n, r) for n, r in report["systems"].items()]
            retrieval = RetrievalReport(
                file=path.name, created=report["created"], git=report["git"], split=split,
                queries=report["queries_scored"], embedding_model=report.get("embedding_model"),
                parser=report.get("parser"),
                systems=sorted(systems, key=lambda s: -s.ndcg.mean),
            )  # fmt: skip
        summary = report.get("summary")
        if parser is None and report.get("split") == split and summary and "exact_match" in summary:
            strict = summary["constraints_strict"]
            parser = ParserReport(
                file=path.name, created=report["created"], git=report["git"],
                split=report["split"], parser=report["parser"],
                model=(report.get("llm") or {}).get("model"), queries=summary["n"],
                intent_accuracy=summary["intent_accuracy"], exact_match=summary["exact_match"],
                constraint_precision=strict["precision"], constraint_recall=strict["recall"],
                constraint_f1=strict["f1"],
            )  # fmt: skip
    return Bench(retrieval=retrieval, parser=parser)
