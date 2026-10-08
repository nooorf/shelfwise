"""Play conversation set C through the conversation service and score the state after every turn.

    uv run python scripts/eval_conversations.py                    # rules-only parser
    uv run python scripts/eval_conversations.py --parser cascade   # the LLM parser (answers cached)
    uv run python scripts/eval_conversations.py --errors           # list every turn that missed

Runs on the real catalog without narration. With --parser cascade, LLM answers come from
eval/data/llm_cache.jsonl; Ollama is only needed for messages not in it yet. Catalog-dependent
values ("shorter" limits, relaxation counts) are scored by field and direction only.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from shelfwise.catalog.db import make_engine
from shelfwise.config import get_settings
from shelfwise.conversation.service import ConversationService, TurnRequest
from shelfwise.conversation.store import MemorySessionStore
from shelfwise.evaluation.conversations import TurnResult, load_conversations, score_turn, summarize
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.evaluation.systems import LLM_CACHE
from shelfwise.pipeline import SearchService

CONVERSATIONS = Path("eval/data/conversations.yaml")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--parser", choices=["rules", "cascade"], default="rules")
    parser.add_argument("--embedding-model", default=get_settings().embedding_model)
    parser.add_argument("--only", nargs="+", metavar="ID", help="just these sessions")
    parser.add_argument("--errors", action="store_true", help="list every turn with a miss")
    parser.add_argument("--file", type=Path, default=CONVERSATIONS)
    args = parser.parse_args()

    gold = load_conversations(args.file)
    sessions = [s for s in gold.sessions if not args.only or s.id in args.only]
    llm = None
    if args.parser == "cascade":
        from shelfwise.llm.cache import CachedLLM
        from shelfwise.llm.client import OllamaClient

        llm = CachedLLM(OllamaClient(), LLM_CACHE)
    from shelfwise.embed.encoder import load_embedder

    search = SearchService(
        embedder=load_embedder(args.embedding_model), today=lambda: gold.today, llm=llm
    )
    conversation = ConversationService(search, MemorySessionStore(ttl_s=3600))
    results: list[TurnResult] = []
    per_session = {}
    with make_engine().connect() as conn:
        for session in sessions:
            session_id = conversation.start()
            shown: list[int] = []
            turns = []
            for number, gold_turn in enumerate(session.turns, start=1):
                if gold_turn.action == "undo":
                    response = conversation.undo(conn, session_id, narrate=False)
                else:
                    request = TurnRequest(message=gold_turn.say, narrate=False)
                    response = conversation.turn(conn, session_id, request)
                state = conversation.store.get(session_id)
                assert state is not None
                positions = None
                if response.route in ("explain", "compare"):
                    positions = [shown.index(r.work_id) + 1 for r in response.results
                                 if r.work_id in shown]  # fmt: skip
                result = score_turn(
                    session.id, number, gold_turn, response.kind, response.route,
                    state.active, state.semantic_query, positions,
                )  # fmt: skip
                results.append(result)
                turns.append({
                    "say": gold_turn.say or f"({gold_turn.action})",
                    "exact": result.exact,
                    "kind": response.kind,
                    "route": response.route,
                    "missing": [str(c) for c in result.missing],
                    "extra": [str(c) for c in result.extra],
                    "keep_missing": result.keep_missing,
                    "leaked": result.leaked,
                    "targets": positions,
                    "semantic_query": state.semantic_query,
                })  # fmt: skip
                if response.route in ("search", "surprise"):
                    shown = [r.work_id for r in response.results]
                print(".", end="", file=sys.stderr, flush=True)
            per_session[session.id] = {"category": session.category, "turns": turns}
    print(file=sys.stderr)

    summary = summarize(results)
    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "parser": args.parser,
        "llm_cache": {"hits": llm.hits, "misses": llm.misses} if llm else None,
        "summary": summary,
        "sessions": per_session,
    }
    if not args.only:
        out = report_path(report["git"], f"conversations-{args.parser}")
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"report: {out}")
    for key, value in summary.items():
        shown_value = f"{value:.1%}" if isinstance(value, float) else value
        print(f"  {key:26} {shown_value}")
    if args.errors:
        for sid, data in per_session.items():
            for i, t in enumerate(data["turns"], start=1):
                if not t["exact"]:
                    details = {k: t[k] for k in ("kind", "route", "missing", "extra",
                                                 "keep_missing", "leaked", "targets") if t[k]}  # fmt: skip
                    print(f"{sid} turn {i} {t['say']!r}: {details}")


if __name__ == "__main__":
    main()
