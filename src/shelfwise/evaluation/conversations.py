"""Conversation set C: scripted sessions with the gold state after every turn.

Lives in `eval/data/conversations.yaml`. Each turn gives what the reader says and what the
conversation state should be afterwards:

    - id: C01
      category: refine
      source: llm-draft
      turns:
        - say: psychological thrillers
          kind: new_search            # what the turn did: new_search, refine, new_topic, ...
          route: search               # search, explain, compare, clarify, surprise, chat, ...
          constraints:                # the WHOLE active set afterwards, PARSING.md lines
            - genre in [thriller] soft
          keep: [psychological]       # words the current search text must contain
        - say: something darker
          kind: refine
          constraints:
            - genre in [thriller] soft
            - facet.darkness gte * soft   # "*": the value depends on what was shown
        - say: tell me about the second one
          kind: reference
          route: explain
          constraints: same           # unchanged from the turn before
          targets: [2]                # positions in the books shown last, 1-based

`action: undo` in place of `say:` presses undo instead of typing. Values that depend on the
catalog (a "shorter" limit, relaxation counts) are never gold; only their field and direction.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from shelfwise.evaluation.parser_gold import GoldConstraint, parse_constraint
from shelfwise.evaluation.parser_metrics import match_constraints, mentions
from shelfwise.evaluation.queries import SOURCES
from shelfwise.query.constraints import Constraint

CATEGORIES = ("refine", "negation", "reference", "topic", "relax", "forget", "chat", "mixed")
KINDS = ("new_search", "refine", "new_topic", "start_over", "reference", "chat", "relax", "undo")
ROUTES = ("search", "explain", "compare", "clarify", "surprise", "chat", "start_over")
ANY = "*"  # a catalog-dependent value: any value matches


@dataclass(frozen=True)
class GoldTurn:
    say: str  # what the reader types; "" for an action
    action: str = ""  # "undo"
    kind: str | None = None
    route: str | None = None
    constraints: tuple[GoldConstraint, ...] | None = ()  # None: not scored (catalog-dependent)
    keep: tuple[str, ...] = ()
    drop: tuple[str, ...] = ()
    targets: tuple[int, ...] = ()  # 1-based positions in the last shown books


@dataclass(frozen=True)
class Session:
    id: str
    category: str
    source: str
    turns: tuple[GoldTurn, ...]
    notes: str = ""


@dataclass(frozen=True)
class ConversationSet:
    today: date
    sessions: list[Session] = field(default_factory=list)


def _constraint(spec: str) -> GoldConstraint:
    words = spec.split()
    if len(words) >= 4 and words[-2] == ANY:  # "facet.darkness gte * soft"
        exclude = words[0] == "not"
        name, op = (words[1], words[2]) if exclude else (words[0], words[1])
        return GoldConstraint(name, op, ANY, words[-1], "exclude" if exclude else "include")
    return parse_constraint(spec)


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where}: expected a list of strings")
    return tuple(value)


def _turn(row: dict[str, Any], previous: tuple[GoldConstraint, ...], where: str) -> GoldTurn:
    unknown = set(row) - {"say", "action", "kind", "route", "constraints", "keep", "drop",
                          "targets"}  # fmt: skip
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    if ("say" in row) == ("action" in row):
        raise ValueError(f"{where}: give exactly one of say / action")
    if row.get("action") not in (None, "undo"):
        raise ValueError(f"{where}: the only action is undo")
    if row.get("kind") not in (None, *KINDS):
        raise ValueError(f"{where}: kind must be one of {KINDS}")
    if row.get("route") not in (None, *ROUTES):
        raise ValueError(f"{where}: route must be one of {ROUTES}")
    spec = row.get("constraints", [])
    constraints: tuple[GoldConstraint, ...] | None
    if spec is None:
        constraints = None  # "constraints: ~": depends on the catalog, not scored
    elif spec == "same":
        constraints = previous
    elif isinstance(spec, list):
        try:
            constraints = tuple(_constraint(str(c)) for c in spec)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
    else:
        raise ValueError(f"{where}: constraints must be a list or 'same'")
    targets = row.get("targets") or []
    if not all(isinstance(t, int) and t >= 1 for t in targets):
        raise ValueError(f"{where}: targets are positions from 1")
    return GoldTurn(
        say=str(row.get("say", "")),
        action=str(row.get("action", "")),
        kind=row.get("kind"),
        route=row.get("route"),
        constraints=constraints,
        keep=_strings(row.get("keep"), where),
        drop=_strings(row.get("drop"), where),
        targets=tuple(targets),
    )


def load_conversations(path: Path) -> ConversationSet:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    today = data["today"]
    sessions, seen = [], set()
    for row in data.get("sessions") or []:
        sid = row.get("id")
        if not sid or sid in seen:
            raise ValueError(f"session {sid!r}: missing or duplicate id")
        seen.add(sid)
        if row.get("category") not in CATEGORIES:
            raise ValueError(f"{sid}: category must be one of {CATEGORIES}")
        if row.get("source") not in SOURCES:
            raise ValueError(f"{sid}: source must be one of {SOURCES}")
        turns: list[GoldTurn] = []
        previous: tuple[GoldConstraint, ...] = ()
        for i, turn_row in enumerate(row.get("turns") or [], start=1):
            turn = _turn(turn_row, previous, f"{sid} turn {i}")
            if turn_row.get("constraints") == "same" and i > 1 and turns[-1].constraints is None:
                raise ValueError(f"{sid} turn {i}: 'same' after an unscored turn")
            turns.append(turn)
            previous = turn.constraints or ()
        if not turns:
            raise ValueError(f"{sid}: no turns")
        sessions.append(Session(sid, row["category"], row["source"], tuple(turns),
                                str(row.get("notes", ""))))  # fmt: skip
    return ConversationSet(today if isinstance(today, date) else date.fromisoformat(today),
                           sessions)  # fmt: skip


def as_gold(constraints: list[Constraint]) -> list[GoldConstraint]:
    return [GoldConstraint(c.field, c.op, c.value, c.strength, c.polarity) for c in constraints]


@dataclass(frozen=True)
class TurnResult:
    session: str
    turn: int
    kind_ok: bool | None  # None: not specified in the gold
    route_ok: bool | None
    missing: list[GoldConstraint]
    extra: list[GoldConstraint]
    matched: int
    keep_missing: list[str]
    leaked: list[str]
    targets_ok: bool | None

    @property
    def exact(self) -> bool:
        return (
            self.kind_ok is not False and self.route_ok is not False and not self.missing
            and not self.extra and not self.keep_missing and not self.leaked
            and self.targets_ok is not False
        )  # fmt: skip


def score_turn(
    session: str, number: int, gold: GoldTurn, kind: str, route: str,
    constraints: list[Constraint], semantic_query: str, target_positions: list[int] | None,
) -> TurnResult:  # fmt: skip
    """`target_positions`: the 1-based positions of the books the reply was about, among
    those shown before the turn (None if it wasn't about shown books)."""
    predicted = as_gold(constraints)
    if gold.constraints is None:
        matched, missing, extra = [], [], []
    else:
        exact_gold = [g for g in gold.constraints if g.value != ANY]
        matched, missing, extra = match_constraints(exact_gold, predicted)
    wild = [g for g in gold.constraints or () if g.value == ANY]
    for g in wild:  # field, op, polarity and strength; any value
        hit = next(
            (p for p in extra if (p.field, p.op, p.polarity, p.strength)
             == (g.field, g.op, g.polarity, g.strength)), None,
        )  # fmt: skip
        if hit is None:
            missing.append(g)
        else:
            extra.remove(hit)
            matched.append(g)
    return TurnResult(
        session=session,
        turn=number,
        kind_ok=None if gold.kind is None else gold.kind == kind,
        route_ok=None if gold.route is None else gold.route == route,
        missing=missing,
        extra=extra,
        matched=len(matched),
        keep_missing=[k for k in gold.keep if not mentions(semantic_query, k)],
        leaked=[d for d in gold.drop if mentions(semantic_query, d)],
        targets_ok=None if not gold.targets else list(gold.targets) == (target_positions or []),
    )


def _share(hits: int, total: int) -> float | None:
    return hits / total if total else None


def summarize(results: list[TurnResult]) -> dict[str, Any]:
    sessions: dict[str, list[TurnResult]] = {}
    for r in results:
        sessions.setdefault(r.session, []).append(r)
    matched = sum(r.matched for r in results)
    gold_total = matched + sum(len(r.missing) for r in results)
    predicted_total = matched + sum(len(r.extra) for r in results)
    precision, recall = _share(matched, predicted_total), _share(matched, gold_total)
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    kinds = [r.kind_ok for r in results if r.kind_ok is not None]
    routes = [r.route_ok for r in results if r.route_ok is not None]
    targets = [r.targets_ok for r in results if r.targets_ok is not None]
    successes = sum(all(r.exact for r in rs) for rs in sessions.values())
    return {
        "sessions": len(sessions),
        "turns": len(results),
        "session_success": _share(successes, len(sessions)),
        "turn_exact": _share(sum(r.exact for r in results), len(results)),
        "state_precision": precision,
        "state_recall": recall,
        "state_f1": f1,
        "kind_accuracy": _share(sum(kinds), len(kinds)),
        "route_accuracy": _share(sum(routes), len(routes)),
        "reference_accuracy": _share(sum(targets), len(targets)),
        "turns_with_leaks": sum(bool(r.leaked) for r in results),
        "turns_missing_keep_words": sum(bool(r.keep_missing) for r in results),
    }
