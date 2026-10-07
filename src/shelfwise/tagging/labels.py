"""Human book tags in a hand-editable CSV: the answers the LLM tagger is scored against.

Kept out of the database on purpose: books are identified by `work_key` (lowest ISBN-13) so labels
survive catalog rebuilds, and the LLM's own tags stay in `work_facets` for comparison. A blank cell
means "can't tell" and is left out of scoring for that tag.
"""

import csv
import hashlib
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Connection, text

from shelfwise.evaluation.agreement import accuracy, cohen_kappa, within_one
from shelfwise.evaluation.judgments import work_keys

type Labels = Mapping[str, str]  # tag name -> value; a missing tag means "can't tell"


@dataclass(frozen=True)
class FacetSpec:
    name: str
    question: str
    options: tuple[tuple[str, str, str], ...]  # (key typed, value stored, text shown)
    scale: Literal["ordinal", "nominal"]
    applies: Callable[[Labels], bool] = field(default=lambda labels: True)

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(value for _, value, _ in self.options)

    def parse(self, key: str) -> str | None:
        return next((value for k, value, _ in self.options if k == key), None)


def _is_fiction(labels: Labels) -> bool:
    return labels.get("fiction") == "yes"


def _is_nonfiction(labels: Labels) -> bool:
    return labels.get("fiction") == "no"


# Same definitions as the LLM rubric (facets.py), in the order a person reads a book's record.
FACETS: tuple[FacetSpec, ...] = (
    FacetSpec(
        "fiction", "Fiction?", (("f", "yes", "fiction"), ("n", "no", "nonfiction")), "nominal"
    ),
    FacetSpec(
        "audience",
        "Audience?",
        (
            ("c", "children", "children (under ~12)"),
            ("y", "ya", "ya (teenage)"),
            ("a", "adult", "adult (everyone else)"),
        ),
        "nominal",
    ),
    FacetSpec(
        "darkness",
        "Darkness?",
        (
            ("0", "0", "light or uplifting"),
            ("1", "1", "some serious moments"),
            ("2", "2", "dark: crime, abuse, grief or violence central"),
            ("3", "3", "very dark: bleak, disturbing, horror"),
        ),
        "ordinal",
    ),
    FacetSpec(
        "romance",
        "Romance?",
        (
            ("0", "0", "none"),
            ("1", "1", "minor subplot"),
            ("2", "2", "significant subplot"),
            ("3", "3", "the central story"),
        ),
        "ordinal",
    ),
    FacetSpec(
        "violence",
        "Violence?",
        (
            ("0", "0", "none"),
            ("1", "1", "mild or off-page"),
            ("2", "2", "on-page"),
            ("3", "3", "graphic or gory"),
        ),
        "ordinal",
    ),
    FacetSpec(
        "pace",
        "Pace?",
        (
            ("1", "slow", "slow"),
            ("2", "medium", "medium (also most nonfiction)"),
            ("3", "fast", "fast"),
        ),
        "ordinal",
    ),
    FacetSpec(
        "supernatural",
        "Supernatural?",
        (
            ("y", "yes", "yes: magic, ghosts, vampires, curses, psychic powers"),
            ("n", "no", "no: realistic, or science-fiction technology"),
            ("u", "unclear", "unclear"),
        ),
        "nominal",
    ),
    FacetSpec(
        "historical_setting",
        "Set in the past (already the past when written)?",
        (
            ("y", "yes", "yes"),
            ("n", "no", "no: the author's present, or the future"),
            ("u", "unclear", "unclear"),
        ),
        "nominal",
        applies=_is_fiction,
    ),
    FacetSpec(
        "reading_level",
        "Reading level?",
        (
            ("i", "intro", "intro: no prior knowledge"),
            ("m", "intermediate", "intermediate: some background"),
            ("a", "advanced", "advanced: graduate or specialist"),
            ("n", "none", "none: not a technical or course book"),
        ),
        "nominal",
        applies=_is_nonfiction,
    ),
)
FACET_BY_NAME = {f.name: f for f in FACETS}
_SCALES_0_3 = {"darkness", "romance", "violence"}
COLUMNS = ("work_key", "judge", *(f.name for f in FACETS), "setting_period", "title")


@dataclass(frozen=True)
class FacetLabel:
    work_key: str
    judge: str
    labels: Labels
    setting_period: str = ""
    title: str = ""


def load_labels(path: Path) -> list[FacetLabel]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}")
        rows, problems = [], []
        for line, row in enumerate(reader, start=2):
            labels = {}
            for spec in FACETS:
                value = (row[spec.name] or "").strip()
                if value and value not in spec.values:
                    problems.append(f"line {line}: {spec.name} must be one of {spec.values}")
                elif value:
                    labels[spec.name] = value
            rows.append(
                FacetLabel(
                    work_key=row["work_key"].strip(),
                    judge=row["judge"].strip(),
                    labels=labels,
                    setting_period=row["setting_period"] or "",
                    title=row["title"] or "",
                )
            )
    if problems:
        raise ValueError(f"{path}:\n  " + "\n  ".join(problems))
    return rows


def save_labels(path: Path, rows: Iterable[FacetLabel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for r in rows:
            values = [r.labels.get(spec.name, "") for spec in FACETS]
            writer.writerow([r.work_key, r.judge, *values, r.setting_period, r.title])
    tmp.replace(path)  # atomic: a crash mid-write never corrupts the file


def upsert_label(rows: list[FacetLabel], new: FacetLabel) -> list[FacetLabel]:
    """One row per (book, judge): re-labelling a book replaces that judge's earlier answer."""
    kept = [r for r in rows if (r.work_key, r.judge) != (new.work_key, new.judge)]
    return [*kept, new]


def labelling_order(books: Mapping[str, str]) -> list[str]:
    """Work keys in a fixed, genre-balanced order: {work_key: primary genre} -> keys.

    Round-robin over primary genres, each genre in hash order. Any prefix (the first 50, the
    first 200) is a spread-out sample, and the order doesn't depend on database ids, so a second
    annotator labelling "the first 50" gets the same books.
    """
    by_genre: dict[str, list[str]] = {}
    for key, genre in books.items():
        by_genre.setdefault(genre, []).append(key)
    queues = [
        sorted(keys, key=lambda k: hashlib.sha1(k.encode()).hexdigest())
        for _, keys in sorted(by_genre.items())
    ]
    order: list[str] = []
    for i in range(max((len(q) for q in queues), default=0)):
        order.extend(q[i] for q in queues if i < len(q))
    return order


def agreement_by_tag(
    reference: Mapping[str, Labels], other: Mapping[str, Labels]
) -> dict[str, dict[str, Any]]:
    """Per-tag agreement of `other` with `reference`, over the books both labelled."""
    results: dict[str, dict[str, Any]] = {}
    for spec in FACETS:
        pairs = [
            (ref[spec.name], other[key][spec.name])
            for key, ref in reference.items()
            if key in other and spec.applies(ref) and spec.name in ref
            and spec.name in other[key]
        ]  # fmt: skip
        if not pairs:
            results[spec.name] = {"n": 0}
            continue
        a, b = [p[0] for p in pairs], [p[1] for p in pairs]
        weights = "quadratic" if spec.scale == "ordinal" else "none"
        results[spec.name] = {
            "n": len(pairs),
            "accuracy": accuracy(a, b),
            "kappa": cohen_kappa(a, b, spec.values, weights),
            "kappa_weights": weights,
            "within_one": within_one(a, b, spec.values) if spec.name in _SCALES_0_3 else None,
            "majority": Counter(a).most_common(1)[0][1] / len(a),
        }
    return results


_LLM_SQL = text(
    """
    SELECT f.work_id, f.fiction, f.audience, f.darkness, f.romance, f.violence, f.pace,
           f.supernatural, f.historical_setting, f.reading_level, f.model_version
    FROM work_facets f
    WHERE f.source = 'llm'
    """
)


def llm_labels(conn: Connection) -> dict[str, tuple[str, Labels]]:
    """The LLM's current tags in label form: {work_key: (model_version, labels)}."""
    keys = work_keys(conn)
    out: dict[str, tuple[str, Labels]] = {}
    for r in conn.execute(_LLM_SQL):
        labels = {
            "fiction": {True: "yes", False: "no"}.get(r.fiction),
            "audience": r.audience,
            **{
                scale: _str_or_none(getattr(r, scale))
                for scale in ("darkness", "romance", "violence")
            },
            "pace": r.pace,
            "supernatural": r.supernatural,
            "historical_setting": r.historical_setting,
            "reading_level": r.reading_level or "none",
        }
        out[keys[r.work_id]] = (r.model_version or "", {k: v for k, v in labels.items() if v})
    return out


def _str_or_none(value: int | None) -> str | None:
    return None if value is None else str(value)
