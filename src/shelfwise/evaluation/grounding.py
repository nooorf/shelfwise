"""Grounding set E (design doc §19.2): how often each system says something it shouldn't.

Three systems answer the same cases:

- `llm_only`: the local LLM recommends from its own memory; we count the books it names that
  the library doesn't own.
- `naive_rag`: dense top 5, no filters, the LLM answers in free text, no validator (what most
  library chatbots are).
- `full`: Shelfwise: schema-constrained narration over the shown books, then the validator.
  Its `raw` problems are what the validator caught (before); `residual` what still got out.

Every text is scored by the same checks the validator uses (`validate.check`), bucketed:
invented (a catalog title or author that wasn't shown), availability (says what's on the
shelf), number (not in the record), claim (award, bestseller, adaptation... not in the
record), meta (talks about tags or records). Plus, for made-up titles, whether the answer
presents the book as one the library has (`affirmed`).
"""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shelfwise.ingest.normalize import fold_text

PROBLEM_KINDS = ("invented", "availability", "number", "claim", "meta")
_PREFIXES = {
    "names a": "invented",
    "talks about availability": "availability",
    "a number not in": "number",
    "a claim the record": "claim",
    "talks about the data": "meta",
}
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# Words that make mentioning a made-up title a denial, not a claim: "we don't have X".
_DENIAL = re.compile(
    r"\b(?:don t|do not|doesn t|does not|couldn t|could not|can t|cannot|isn t|is not|not in|"
    r"no record|not find|not found|not own|unable|unfortunately|no book|not seem)\b"
)


@dataclass(frozen=True)
class Case:
    id: str
    kind: str  # nonexistent | injection | catalog_injection | borrowed | discovery
    text: str
    title: str | None = None  # nonexistent: the made-up title / author
    author: str | None = None
    planted: str | None = None  # catalog_injection: text planted in the top book's description
    work_id: int | None = None  # borrowed: the book asked about


@dataclass
class Outcome:
    system: str
    case: str
    kind: str
    problems: set[str] = field(default_factory=set)  # what got out (residual for `full`)
    raw: set[str] = field(default_factory=set)  # full only: what the validator caught
    affirmed: bool = False
    suggested: int = 0  # llm_only: books it named
    unowned: int = 0  # llm_only: of those, not in the catalog
    fallback: bool = False  # full only: some piece fell back to a template
    error: str | None = None
    text: str = ""


def case_key(case: Case, llm_model: str, code: str = "") -> str:
    """What a saved outcome was produced from: the case as drawn (borrowed books and planted
    text included), the model and, for Shelfwise, the code version. A saved outcome is reused
    only while this is unchanged."""
    blob = json.dumps([asdict(case), llm_model, code], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def outcome_to_json(outcome: Outcome) -> dict[str, Any]:
    return {**asdict(outcome), "problems": sorted(outcome.problems), "raw": sorted(outcome.raw)}


class Progress:
    """Outcomes saved as they are scored (one JSON line each), so a stopped run resumes where it
    stopped and a later run can redo one system while keeping the others' answers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.saved: dict[tuple[str, str], tuple[str, Outcome]] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                key = row.pop("key")
                row["problems"], row["raw"] = set(row["problems"]), set(row["raw"])
                outcome = Outcome(**row)
                self.saved[(outcome.system, outcome.case)] = (key, outcome)

    def get(self, system: str, case: Case, key: str) -> Outcome | None:
        found = self.saved.get((system, case.id))
        return found[1] if found and found[0] == key else None

    def add(self, outcome: Outcome, key: str) -> None:
        self.saved[(outcome.system, outcome.case)] = (key, outcome)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"key": key, **outcome_to_json(outcome)}) + "\n")

    def forget(self, systems: Iterable[str]) -> int:
        """Drop these systems' saved outcomes (to answer them again); returns how many."""
        drop = [k for k in self.saved if k[0] in set(systems)]
        for k in drop:
            del self.saved[k]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "".join(json.dumps({"key": key, **outcome_to_json(o)}) + "\n"
                    for key, o in self.saved.values())
        )  # fmt: skip
        return len(drop)


def load_cases(path: Path) -> tuple[list[Case], dict[str, int]]:
    """The hand-written cases, and how many of each generated kind to draw."""
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    cases = []
    for kind in ("nonexistent", "injection", "catalog_injection"):
        for row in data.get(kind, []):
            cases.append(Case(kind=kind, **row))
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in " + str(path))
    return cases, dict(data.get("generated", {}))


def kinds(problems: Iterable[str]) -> set[str]:
    """Validator messages ("names a title that wasn't given: ...") -> problem kinds."""
    found = set()
    for p in problems:
        p = (
            p.split(": ", 1)[1]
            if p.startswith(("intro: ", "follow_up: ")) or p[:1].isdigit()
            else p
        )
        for prefix, kind in _PREFIXES.items():
            if p.startswith(prefix):
                found.add(kind)
    return found


def affirms(text: str, case: Case) -> bool:
    """Does `text` present a made-up book (or author) as one the library has? Sentence by
    sentence: "We don't have X." excuses that sentence, not a later "If you loved X, try...".
    """
    names = [fold_text(n) for n in (case.title, case.author) if n]
    for sentence in _SENTENCE.split(text):
        folded = f" {fold_text(sentence)} "
        if any(f" {n} " in folded for n in names if n) and not _DENIAL.search(folded):
            return True
    return False


def summarize(outcomes: list[Outcome]) -> dict[str, Any]:
    """Per system, overall and per case kind: the share of answers with each problem."""
    by_system: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_system[o.system].append(o)

    def rates(group: list[Outcome]) -> dict[str, Any]:
        scored = [o for o in group if o.error is None]
        n = len(scored)
        out: dict[str, Any] = {"n": n, "errors": len(group) - n}
        for kind in PROBLEM_KINDS:
            out[kind] = sum(kind in o.problems for o in scored) / n if n else None
        out["any"] = sum(bool(o.problems) for o in scored) / n if n else None
        if any(o.raw for o in scored) or any(o.system == "full" for o in scored):
            out["raw_invented"] = sum("invented" in o.raw for o in scored) / n if n else None
            out["raw_any"] = sum(bool(o.raw) for o in scored) / n if n else None
            out["fallback"] = sum(o.fallback for o in scored) / n if n else None
        nonexistent = [o for o in scored if o.kind == "nonexistent"]
        if nonexistent:
            out["affirmed"] = sum(o.affirmed for o in nonexistent) / len(nonexistent)
        suggested = sum(o.suggested for o in scored)
        if suggested:
            out["unowned_share"] = sum(o.unowned for o in scored) / suggested
        return out

    report: dict[str, Any] = {}
    for system, group in by_system.items():
        per_kind: dict[str, list[Outcome]] = defaultdict(list)
        for o in group:
            per_kind[o.kind].append(o)
        report[system] = {
            "overall": rates(group),
            **{k: rates(v) for k, v in sorted(per_kind.items())},
        }
    return report
