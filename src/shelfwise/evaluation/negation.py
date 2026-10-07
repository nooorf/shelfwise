"""Paired negation queries for the negation study (design doc §40.1 B).

Each pair is a base request and the same request with one thing ruled out ("a creepy gothic
novel" / "... with nothing supernatural"). `negation_pairs.csv` says, per pair, which book tag
value counts as a violation of the negation, in the vocabulary of the human tag labels:

    supernatural=yes    romance>=2    violence>=3    audience=children

The study compares how often each system returns violating books for the negated query, against
the base query's rate (how common the attribute is anyway). Violations are judged from *human*
labels, never from the LLM tags the facet filter uses, or the study would grade itself.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from shelfwise.evaluation.queries import Query
from shelfwise.tagging.labels import FACET_BY_NAME, Labels

COLUMNS = ("pair", "attribute", "violation", "base", "negated")
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

    def check(self, labels: Labels) -> bool | None:
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
            NegationPair(values["pair"], values["attribute"], violation, base.id, negated.id)
        )

    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return pairs
