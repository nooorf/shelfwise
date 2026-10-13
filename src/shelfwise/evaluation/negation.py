"""Paired negation queries for the negation study.

Each pair is a base request and the same request with one thing ruled out ("a creepy gothic
novel" / "... with nothing supernatural"). `negation_pairs.csv` says, per pair, which book tag
value counts as a violation of the negation, in the vocabulary of the human tag labels:

    supernatural=yes    romance>=2    violence>=3    audience=children

The study compares how often each system returns violating books for the negated query, against
the base query's rate (how common the attribute is anyway). Violations are judged from *human*
labels, never from the LLM tags the facet filter uses, or the study would grade itself.
"""

import csv
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from shelfwise.evaluation.agreement import accuracy, cohen_kappa
from shelfwise.evaluation.judgments import Judgment
from shelfwise.evaluation.queries import Query
from shelfwise.tagging.labels import FACET_BY_NAME, FacetLabel

COLUMNS = ("pair", "attribute", "violation", "kind", "base", "negated")
# remove: the ruled-out thing is common in the base's results; can the system take it out?
# lure: it's rare in the base; does naming it in the negation drag it in (the NevIR failure)?
KINDS = ("remove", "lure")
_SPEC = re.compile(r"^(?P<facet>[a-z_]+)(?P<op>>=|=)(?P<value>[a-z0-9]+)$")
_SCALES = {"darkness", "romance", "violence"}


@dataclass(frozen=True)
class Violation:
    facet: str
    op: str  # "=" or ">=" (0-3 scales only)
    value: str

    @classmethod
    def parse(cls, spec: str) -> "Violation":
        match = _SPEC.match(spec.strip())
        if not match:
            raise ValueError(f"{spec!r}: expected facet=value or facet>=n")
        facet, op, value = match["facet"], match["op"], match["value"]
        if facet not in FACET_BY_NAME:
            raise ValueError(f"{spec!r}: unknown tag {facet!r}")
        if value not in FACET_BY_NAME[facet].values:
            raise ValueError(f"{spec!r}: {facet} has no value {value!r}")
        if op == ">=" and facet not in _SCALES:
            raise ValueError(f"{spec!r}: >= only works on 0-3 scales")
        return cls(facet, op, value)

    def check(self, labels: Mapping[str, str | None]) -> bool | None:
        """Does a book with these labels violate the negation? None: not labelled, or unclear."""
        label = labels.get(self.facet)
        if label is None or label == "unclear":
            return None
        if self.op == ">=":
            return int(label) >= int(self.value)
        return label == self.value

    def __str__(self) -> str:
        return f"{self.facet}{self.op}{self.value}"


@dataclass(frozen=True)
class NegationPair:
    pair: str
    attribute: str
    violation: Violation
    base: str  # query ids
    negated: str
    kind: str = "remove"


def load_pairs(path: Path, queries: dict[str, Query]) -> list[NegationPair]:
    """Load and validate against the queries; raises ValueError listing every problem."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}")
        rows = list(reader)

    problems: list[str] = []
    pairs: list[NegationPair] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        values = {k: (row.get(k) or "").strip() for k in COLUMNS}
        where = f"line {line} ({values['pair'] or '?'})"
        if values["pair"] in seen:
            problems.append(f"{where}: duplicate pair")
        seen.add(values["pair"])
        try:
            violation = Violation.parse(values["violation"])
        except ValueError as error:
            problems.append(f"{where}: {error}")
            continue
        if values["kind"] not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if violation.facet != values["attribute"]:
            problems.append(
                f"{where}: violation is about {violation.facet}, not {values['attribute']}"
            )
        base, negated = queries.get(values["base"]), queries.get(values["negated"])
        if base is None or negated is None:
            problems.append(f"{where}: unknown query id {values['base']} or {values['negated']}")
            continue
        if base.family != negated.family:
            problems.append(f"{where}: base and negated must share a family (one split)")
        if negated.category != "negation":
            problems.append(f"{where}: {negated.id} must have category negation")
        pairs.append(
            NegationPair(
                values["pair"], values["attribute"], violation, base.id, negated.id, values["kind"]
            )
        )

    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return pairs


# --- Human answers for the study: one tag per book ------------------------------------------

LABEL_COLUMNS = ("work_key", "judge", "facet", "value", "title")


@dataclass(frozen=True)
class ViolationLabel:
    """One person's answer to one tag question about one book. A blank value: can't tell."""

    work_key: str
    judge: str
    facet: str
    value: str
    title: str = ""


def load_violation_labels(path: Path) -> list[ViolationLabel]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != LABEL_COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(LABEL_COLUMNS)}")
        rows, problems = [], []
        for line, row in enumerate(reader, start=2):
            label = ViolationLabel(*((row.get(k) or "").strip() for k in LABEL_COLUMNS))
            spec = FACET_BY_NAME.get(label.facet)
            if spec is None:
                problems.append(f"line {line}: unknown tag {label.facet!r}")
            elif label.value and label.value not in spec.values:
                problems.append(f"line {line}: {label.facet} must be one of {spec.values}")
            rows.append(label)
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return rows


def save_violation_labels(path: Path, rows: Iterable[ViolationLabel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(LABEL_COLUMNS)
        for r in sorted(rows, key=lambda r: (r.facet, r.work_key, r.judge)):
            writer.writerow([r.work_key, r.judge, r.facet, r.value, r.title.strip()])
    tmp.replace(path)  # atomic: a crash mid-write never corrupts the file


def upsert_violation_label(rows: list[ViolationLabel], new: ViolationLabel) -> list[ViolationLabel]:
    """One answer per (book, tag, judge): answering again replaces the earlier one."""
    key = (new.work_key, new.facet, new.judge)
    return [*(r for r in rows if (r.work_key, r.facet, r.judge) != key), new]


def human_tags(
    violation_labels: Iterable[ViolationLabel],
    facet_labels: Iterable[FacetLabel],
    judge: str,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, dict[str, str | None]]:
    """{work_key: {tag: value}} from one judge's answers in both files, including the labels they
    reviewed ("<judge>-review"). None means "asked, can't tell", so the book isn't asked again. A
    one-tag answer overrides the full label."""
    aliases = aliases or {}
    tags: dict[str, dict[str, str | None]] = {}
    for row in facet_labels:
        if row.judge in (judge, f"{judge}-review"):
            tags.setdefault(aliases.get(row.work_key, row.work_key), {}).update(row.labels)
    for label in violation_labels:
        if label.judge == judge:
            book = tags.setdefault(aliases.get(label.work_key, label.work_key), {})
            book[label.facet] = label.value or None
    return tags


@dataclass(frozen=True)
class Question:
    work_key: str
    facet: str
    title: str
    pairs: tuple[str, ...]  # the pairs whose results include this book


def questions(
    pairs: Iterable[NegationPair],
    judgments: Iterable[Judgment],
    known: Mapping[str, Mapping[str, str | None]],
    aliases: Mapping[str, str] | None = None,
) -> list[Question]:
    """One question per (pooled book, tag) still unanswered, for the books pooled for either
    query of each pair (the base query's books give the base rate). In pair order, then by title.
    """
    aliases = aliases or {}
    titles: dict[str, str] = {}
    pooled: dict[str, set[str]] = {}
    for j in judgments:
        key = aliases.get(j.work_key, j.work_key)
        pooled.setdefault(j.query_id, set()).add(key)
        titles.setdefault(key, j.title)
    found: dict[tuple[str, str], list[str]] = {}
    for pair in pairs:
        books = pooled.get(pair.base, set()) | pooled.get(pair.negated, set())
        for key in sorted(books, key=lambda k: (titles[k].lower(), k)):
            if pair.attribute not in known.get(key, {}):
                found.setdefault((key, pair.attribute), []).append(pair.pair)
    return [
        Question(key, facet, titles[key], tuple(pair_ids))
        for (key, facet), pair_ids in found.items()
    ]


# --- Blind check of one judge's answers by another -----------------------------------------


def blind_sample(
    labels: Iterable[ViolationLabel], reference: str, per_tag: int = 10, seed: int = 0
) -> list[tuple[str, str]]:
    """(work_key, tag) questions to ask a second person, drawn from `reference`'s answers: up to
    `per_tag` per tag, spread evenly over the values given (so rare answers like supernatural=yes
    on a mystery shelf are checked too), deterministic for a seed. "Can't tell" answers are left
    out: there is nothing to agree with."""
    rng = random.Random(seed)
    by_tag: dict[str, dict[str, list[str]]] = {}
    for label in labels:
        if label.judge == reference and label.value:
            by_tag.setdefault(label.facet, {}).setdefault(label.value, []).append(label.work_key)
    picked: list[tuple[str, str]] = []
    for tag in sorted(by_tag):
        pools = {value: sorted(keys) for value, keys in sorted(by_tag[tag].items())}
        for keys in pools.values():
            rng.shuffle(keys)
        chosen: list[str] = []
        while len(chosen) < per_tag and any(pools.values()):
            for value in list(pools):
                if pools[value] and len(chosen) < per_tag:
                    chosen.append(pools[value].pop())
        picked += [(key, tag) for key in chosen]
    return picked


def violation_agreement(
    labels: Iterable[ViolationLabel], pairs: Iterable[NegationPair], judge_a: str, judge_b: str
) -> dict[str, dict]:
    """Per tag, over the questions both judges answered (neither "can't tell"): how often they
    gave the same value, Cohen's kappa (quadratic on the 0-3 scales and pace), and how often
    they agree on what the study counts: whether the book breaks each pair's negation."""
    answers: dict[tuple[str, str], dict[str, str]] = {}
    for label in labels:
        if label.judge in (judge_a, judge_b) and label.value:
            answers.setdefault((label.work_key, label.facet), {})[label.judge] = label.value
    both = {k: v for k, v in answers.items() if judge_a in v and judge_b in v}
    violations: dict[str, list[Violation]] = {}
    for pair in pairs:
        violations.setdefault(pair.attribute, []).append(pair.violation)
    results: dict[str, dict] = {}
    for tag in sorted({tag for _, tag in both}):
        a = [v[judge_a] for (_, t), v in both.items() if t == tag]
        b = [v[judge_b] for (_, t), v in both.items() if t == tag]
        spec = FACET_BY_NAME[tag]
        weights = "quadratic" if spec.scale == "ordinal" else "none"
        decided = [
            (rule.check({tag: x}), rule.check({tag: y}))
            for x, y in zip(a, b, strict=True)
            for rule in {str(r): r for r in violations.get(tag, [])}.values()
        ]
        results[tag] = {
            "n": len(a),
            "accuracy": accuracy(a, b),
            "kappa": cohen_kappa(a, b, spec.values, weights),
            "violation_agreement": (
                sum(x == y for x, y in decided) / len(decided) if decided else None
            ),
        }
    return results
