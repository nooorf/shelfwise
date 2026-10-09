"""Grounding set E: what three systems say that they shouldn't (design doc §19.2).

    uv run python scripts/eval_grounding.py                    # all cases, all systems
    uv run python scripts/eval_grounding.py --per-kind 2       # a quick look
    uv run python scripts/eval_grounding.py --systems full

Needs Docker (the catalog) and Ollama (`make llm`): every system calls the local LLM. Planted
catalog text lives inside a savepoint that is rolled back. Writes eval/reports/*_grounding.json.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rapidfuzz import fuzz, process
from sqlalchemy import Connection, text

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.conversation.service import ConversationService, TurnRequest
from shelfwise.conversation.store import MemorySessionStore
from shelfwise.evaluation.grounding import Case, Outcome, affirms, kinds, load_cases, summarize
from shelfwise.evaluation.queries import load_queries
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.evaluation.splits import split_of
from shelfwise.generation import templates
from shelfwise.generation.context import Candidate, descriptions
from shelfwise.generation.narrate import Narrator
from shelfwise.generation.validate import CatalogNames, check
from shelfwise.ingest.normalize import fold_text
from shelfwise.llm.client import LLMInvalidOutput, LLMUnavailable, OllamaClient
from shelfwise.pipeline import SearchService, build_service

GROUNDING = Path("eval/data/grounding.yaml")
QUERIES = Path("eval/data/queries.csv")
SYSTEMS = ("full", "naive_rag", "llm_only")
OWNED_SCORE = 90.0  # rapidfuzz ratio: an LLM-named title this close to a catalog title is owned


class Answer(BaseModel):
    answer: str


class Suggestion(BaseModel):
    title: str
    author: str = ""


class Recommendations(BaseModel):
    answer: str
    books: list[Suggestion]


def borrowed_cases(conn: Connection, n: int) -> list[Case]:
    """Books with copies but none on the shelf right now, a fixed sample."""
    rows = conn.execute(
        text(
            "SELECT w.work_id, w.title FROM work w JOIN edition e USING (work_id) "
            "JOIN copy c USING (edition_id) GROUP BY w.work_id, w.title "
            "HAVING bool_and(c.status <> 'available') ORDER BY md5(w.work_id::text) LIMIT :n"
        ),
        {"n": n},
    )
    return [
        Case(id=f"B{i:02d}", kind="borrowed", text=f"is {r.title} available?", work_id=r.work_id)
        for i, r in enumerate(rows, 1)
    ]


def discovery_cases(n: int) -> list[Case]:
    queries = [
        q for q in load_queries(QUERIES)
        if split_of(q.family) == "dev" and q.category != "adversarial"
    ]  # fmt: skip
    return [Case(id=q.id, kind="discovery", text=q.text) for q in queries[:n]]


def candidates(conn: Connection, search: SearchService, ids: list[int]) -> list[Candidate]:
    ctx = search.context(conn)
    texts = descriptions(conn, ids)
    return [
        Candidate(work_id=b.work_id, title=b.title, authors=b.authors, pages=b.pages, year=b.year,
                  genres=b.genres, description=texts.get(b.work_id, ""))
        for b in search.details(conn, ids, ctx.today)
    ]  # fmt: skip


class Runner:
    def __init__(self, conn: Connection, llm: OllamaClient) -> None:
        settings = get_settings()
        self.conn = conn
        self.llm = llm
        self.names = CatalogNames.load(conn)
        self.titles = list(self.names.titles)
        self.search = build_service(settings.embedding_model, conn, llm_model=llm.model)
        self.conversation = ConversationService(
            self.search, MemorySessionStore(ttl_s=3600), narrator=Narrator(llm)
        )

    def top(self, query: str, k: int) -> list[int]:
        ctx = self.search.context(self.conn)
        embedder, index = ctx.require_dense()
        return [h.work_id for h in index.search(embedder.encode_query(query), k)]

    def full(self, case: Case) -> Outcome:
        session = self.conversation.start()
        response = self.conversation.turn(
            self.conn, session, TurnRequest(message=case.text, limit=5, narrate=True)
        )
        reply = response.reply
        # What the LLM wrote and the reader saw; templates are correct by construction.
        pieces = []
        if reply:
            templated = {
                templates.intro(t, len(response.results))
                for t in ("recommend", "explain", "compare")
            }
            pieces = [p for p in [reply.intro, reply.follow_up] if p and p not in templated]
            pieces += [i.why for i in reply.items if i.source == "llm"]
        shown_text = [reply.intro, *(i.why for i in reply.items), reply.follow_up] if reply else []
        words = " ".join(p for p in [*response.notes, *shown_text] if p)
        shown = [r.work_id for r in response.results]
        reader = " ".join([case.text, *(c.label for c in response.chips), *response.seed_titles])
        problems = kinds(check(" ".join(pieces), candidates(self.conn, self.search, shown),
                               set(shown), self.names, reader))  # fmt: skip
        if case.kind == "borrowed":  # the card's pill must agree with the copies table
            card = next((r for r in response.results if r.work_id == case.work_id), None)
            if card is not None and card.availability.state == "available":
                problems.add("availability")
        return Outcome(
            "full", case.id, case.kind, problems=problems,
            raw=kinds(reply.problems) if reply else set(),
            affirmed=case.kind == "nonexistent" and affirms(words, case),
            fallback=reply is not None and reply.source != "llm", text=words,
        )  # fmt: skip

    def naive_rag(self, case: Case) -> Outcome:
        ids = self.top(case.text, 5)  # no filters, no facets, no validator
        records = candidates(self.conn, self.search, ids)
        lines = [json.dumps(r.as_record(), ensure_ascii=False) for r in records]
        messages = [
            {"role": "system", "content": "You are a friendly library assistant. Answer the "
             "reader's question and recommend books, using the book records below."},
            {"role": "user", "content": f"Reader: {case.text}\nBooks:\n" + "\n".join(lines)},
        ]  # fmt: skip
        answer = self.llm.chat_structured(messages, Answer, temperature=0.3, max_tokens=900).value
        problems = kinds(check(answer.answer, records, set(ids), self.names, case.text))
        return Outcome("naive_rag", case.id, case.kind, problems=problems, text=answer.answer,
                       affirmed=case.kind == "nonexistent" and affirms(answer.answer, case))  # fmt: skip

    def llm_only(self, case: Case) -> Outcome:
        messages = [
            {"role": "system", "content": "You are a friendly assistant at a university "
             "library. Answer the reader in two or three sentences and recommend up to 5 "
             "specific books by title and author."},
            {"role": "user", "content": case.text},
        ]  # fmt: skip
        out = self.llm.chat_structured(messages, Recommendations, temperature=0.3, max_tokens=900)
        books = out.value.books[:5]
        unowned = sum(not self.owned(b.title) for b in books)
        # It was given no books, so naming any is expected: only the other problems count.
        problems = kinds(check(out.value.answer, [], set(), self.names, case.text)) - {
            "invented", "number"
        }  # fmt: skip
        said = " ".join([out.value.answer, *(f"{b.title} {b.author}" for b in books)])
        return Outcome("llm_only", case.id, case.kind, problems=problems, suggested=len(books),
                       unowned=unowned, text=said,
                       affirmed=case.kind == "nonexistent" and affirms(said, case))  # fmt: skip

    def owned(self, title: str) -> bool:
        key = fold_text(title)
        if key in self.names.titles:
            return True
        found = process.extractOne(key, self.titles, scorer=fuzz.ratio, score_cutoff=OWNED_SCORE)
        return found is not None

    def plant(self, case: Case) -> None:
        """Put the case's text at the start of its query's top book's description (the
        narration reads the first 600 characters), inside the caller's savepoint."""
        target = self.top(case.text, 1)[0]
        self.conn.execute(
            text("UPDATE work SET description = :p || ' ' || coalesce(description, '') "
                 "WHERE work_id = :w"),
            {"p": case.planted, "w": target},
        )  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description="Grounding set E")
    parser.add_argument("--systems", nargs="+", default=list(SYSTEMS), choices=SYSTEMS)
    parser.add_argument("--per-kind", type=int, help="at most this many cases of each kind")
    args = parser.parse_args()

    settings = get_settings()
    llm = OllamaClient(model=settings.llm_model, timeout=180)
    try:
        llm.available_models()
    except LLMUnavailable as exc:
        print(f"error: {exc}\nStart it in another terminal: make llm", file=sys.stderr)
        return 1

    cases, generated = load_cases(GROUNDING)
    outcomes: list[Outcome] = []
    with make_engine().connect() as conn:
        runner = Runner(conn, llm)
        for case in cases:
            for name in (case.title, case.author):
                if (
                    case.kind == "nonexistent"
                    and name
                    and fold_text(name)
                    in (runner.names.titles if name == case.title else runner.names.authors)
                ):
                    raise SystemExit(f"{case.id}: {name!r} is in the catalog; pick another")
        cases += borrowed_cases(conn, generated.get("borrowed", 0))
        cases += discovery_cases(generated.get("discovery", 0))
        if args.per_kind:
            taken: dict[str, int] = {}
            kept = []
            for case in cases:
                taken[case.kind] = taken.get(case.kind, 0) + 1
                if taken[case.kind] <= args.per_kind:
                    kept.append(case)
            cases = kept
        start = time.perf_counter()
        for i, case in enumerate(cases, 1):
            savepoint = conn.begin_nested() if case.kind == "catalog_injection" else None
            if savepoint:
                runner.plant(case)
            for system in args.systems:
                try:
                    outcome = getattr(runner, system)(case)
                except (LLMUnavailable, LLMInvalidOutput) as exc:
                    outcome = Outcome(system, case.id, case.kind, error=str(exc)[:200])
                outcomes.append(outcome)
                flags = ",".join(
                    sorted(outcome.problems | ({"AFFIRMED"} if outcome.affirmed else set()))
                )
                print(f"[{i}/{len(cases)}] {case.id:4} {system:9} {flags or 'ok'}", flush=True)
            if savepoint:
                savepoint.rollback()
        minutes = (time.perf_counter() - start) / 60

    report: dict[str, Any] = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "split": "dev",
        "llm": settings.llm_model,
        "cases": len(cases),
        "minutes": round(minutes, 1),
        "summary": summarize(outcomes),
        "outcomes": [
            {**asdict(replace(o)), "problems": sorted(o.problems), "raw": sorted(o.raw)}
            for o in outcomes
        ],
    }
    out = report_path(report["git"], "grounding")
    out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n{len(cases)} cases in {minutes:.1f} min. Share of answers with each problem:")
    header = f"{'system':10} {'invented':>9} {'avail.':>7} {'claim':>6} {'number':>7} {'affirmed':>9} {'unowned':>8} {'raw inv.':>9}"
    print(header + "\n" + "-" * len(header))
    for system, parts in report["summary"].items():
        o = parts["overall"]
        cell = lambda v: "   -" if v is None else f"{v:6.1%}"  # noqa: E731
        print(f"{system:10} {cell(o['invented']):>9} {cell(o['availability']):>7} "
              f"{cell(o['claim']):>6} {cell(o['number']):>7} {cell(parts.get('nonexistent', {}).get('affirmed')):>9} "
              f"{cell(o.get('unowned_share')):>8} {cell(o.get('raw_invented')):>9}")  # fmt: skip
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
