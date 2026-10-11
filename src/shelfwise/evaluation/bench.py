"""The `/bench` page's data (design doc §22.2): the newest retrieval, parser, grounding and voice
reports from `eval/reports`, trimmed to what the dashboard draws (no per-query rows)."""

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


class GroundingRates(BaseModel):
    """Share of a system's answers with each problem (set E, `evaluation.grounding`)."""

    name: str
    answers: int
    invented: float | None
    availability: float | None
    claim: float | None
    number: float | None
    affirmed: float | None = None  # made-up books presented as owned
    unowned: float | None = None  # llm_only: suggestions the library doesn't own
    raw_invented: float | None = None  # full: invented names the validator caught


class GroundingReport(BaseModel):
    file: str
    created: str
    git: str
    llm: str
    cases: int
    systems: list[GroundingRates]


class Spread(BaseModel):
    n: int
    mean: float
    p50: float
    p95: float


class Offset(Spread):
    abs_p95: float  # p95 of the offset's size, either direction


class Difference(Spread):
    ci95: tuple[float, float] | None = None  # the mean's bootstrap 95% CI


class VoiceCondition(BaseModel):
    """One run of the spoken questions (`make measure`), avatar on or off; times in ms."""

    questions: int
    answered: int  # with a first audio measured
    ttfa: Spread | None  # end of the question's speech -> first sound of the answer
    stages: dict[str, float] | None  # mean ms per stage, in order; they add up to the mean TTFA
    first_note: Spread | None  # end of speech -> the LLM's first book note on screen
    av_offset: Offset | None  # mouth opening minus sound starting; positive: lips late
    fps: Spread | None  # avatar frames per second while speaking, per answer
    fps_p5: float | None


class AvatarLoad(BaseModel):
    first_frame_ms: Spread | None  # from navigation to the avatar's first frame, cold cache
    model_ms: Spread | None  # the model's download and parse alone


class VoiceReport(BaseModel):
    file: str
    created: str
    git: str
    parser: str | None
    browser: str
    machine: str
    avatar_model: str
    questions: int
    off: VoiceCondition
    on: VoiceCondition
    avatar_cost_ms: Difference | None  # TTFA avatar on minus off, question by question
    avatar_load: AvatarLoad


class Bench(BaseModel):
    retrieval: RetrievalReport | None
    parser: ParserReport | None
    grounding: GroundingReport | None = None
    voice: VoiceReport | None = None


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
    retrieval = parser = grounding = voice = None
    for path, report in _reports(folder):
        if voice is None and path.name.endswith("_voice.json"):
            conditions = report["conditions"]
            voice = VoiceReport(
                file=path.name, created=report["created"], git=report["git"],
                parser=report.get("parser"), browser=report["browser"], machine=report["machine"],
                avatar_model=report["avatar_model"], questions=len(report["questions"]),
                off=VoiceCondition.model_validate(conditions["off"]),
                on=VoiceCondition.model_validate(conditions["on"]),
                avatar_cost_ms=report.get("avatar_cost_ms"),
                avatar_load=AvatarLoad.model_validate(report["avatar_load"]),
            )  # fmt: skip
            continue
        if grounding is None and path.name.endswith("_grounding.json"):
            order = {"llm_only": 0, "naive_rag": 1, "full": 2}
            systems = [
                GroundingRates(
                    name=name, answers=parts["overall"]["n"],
                    invented=parts["overall"]["invented"],
                    availability=parts["overall"]["availability"],
                    claim=parts["overall"]["claim"], number=parts["overall"]["number"],
                    affirmed=parts.get("nonexistent", {}).get("affirmed"),
                    unowned=parts["overall"].get("unowned_share"),
                    raw_invented=parts["overall"].get("raw_invented"),
                )
                for name, parts in sorted(report["summary"].items(), key=lambda kv: order.get(kv[0], 9))
            ]  # fmt: skip
            grounding = GroundingReport(
                file=path.name, created=report["created"], git=report["git"], llm=report["llm"],
                cases=report["cases"], systems=systems,
            )  # fmt: skip
            continue
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
    return Bench(retrieval=retrieval, parser=parser, grounding=grounding, voice=voice)
