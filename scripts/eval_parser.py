"""Score a query parser against gold set B; print a summary and save a JSON report.

    uv run python scripts/eval_parser.py                     # rules-only baseline, dev split
    uv run python scripts/eval_parser.py --split all --errors
    uv run python scripts/eval_parser.py --only BM04 N03     # just these queries, with errors

Relative dates resolve against the gold file's `today`, so scores don't drift with the calendar.
Rules for the gold set: eval/PARSING.md.
"""

import argparse
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from shelfwise.evaluation.parser_gold import load_gold
from shelfwise.evaluation.parser_metrics import QueryResult, score_query, summarize
from shelfwise.evaluation.reports import git_version, report_path
from shelfwise.evaluation.splits import split_of
from shelfwise.query.request import ParsedRequest, parse_rules_only

GOLD = Path("eval/data/parser_gold.yaml")
QUERIES = Path("eval/data/queries.csv")

PARSERS: dict[str, Callable[[str, date], ParsedRequest]] = {"rules": parse_rules_only}


def _pct(value: float | None) -> str:
    return "   n/a" if value is None else f"{value:6.1%}"


def _print_errors(results: list[QueryResult], texts: dict[str, str]) -> None:
    for r in results:
        if r.exact and not r.leaked and r.keep_found == r.keep_total:
            continue
        print(f"\n{r.id}  {texts[r.id]}")
        if not r.intent_ok:
            print(f"  intent   {r.intent} (gold {r.gold_intent})")
        if not r.lookup_ok:
            print("  lookup   wrong")
        if not r.seeds_ok:
            print("  seeds    wrong")
        for c in r.missing:
            print(f"  missing  {c}")
        for c in r.extra:
            print(f"  extra    {c}")
        if r.keep_found < r.keep_total:
            print(f"  keep     {r.keep_found}/{r.keep_total} found in the semantic query")
        if r.leaked:
            print(f"  leaked   {', '.join(r.leaked)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--parser", choices=list(PARSERS), default="rules")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--only", nargs="+", metavar="ID", help="score just these query ids")
    parser.add_argument("--errors", action="store_true", help="list every query with a mistake")
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--queries", type=Path, default=QUERIES)
    args = parser.parse_args()

    gold = load_gold(args.gold, args.queries)
    golds = [
        g
        for g in gold.queries
        if (args.only and g.id in args.only)
        or (not args.only and (args.split == "all" or split_of(g.family) == args.split))
    ]
    if not golds:
        raise SystemExit("No gold queries selected.")
    parse = PARSERS[args.parser]
    predicted = {g.id: parse(g.text, gold.today) for g in golds}
    results = [score_query(g, predicted[g.id]) for g in golds]
    summary = summarize(results)

    report = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_version(),
        "parser": args.parser,
        "split": "only" if args.only else args.split,
        "today": gold.today.isoformat(),
        "summary": summary.as_dict(),
        "per_query": {
            r.id: {
                "exact": r.exact,
                "intent": r.intent,
                "missing": [str(c) for c in r.missing],
                "extra": [str(c) for c in r.extra],
                "leaked": r.leaked,
                "predicted": predicted[r.id].model_dump(mode="json"),
            }
            for r in results
        },
    }
    out = None if args.only else report_path(report["git"], f"parser-{args.parser}-{args.split}")
    if out:
        out.write_text(json.dumps(report, indent=2))

    print(f"{args.parser} parser, {report['split']} split: {summary.n} queries")
    print(f"  exact match       {_pct(summary.exact_match)}")
    print(f"  intent accuracy   {_pct(summary.intent_accuracy)}")
    print(f"  lookup accuracy   {_pct(summary.lookup_accuracy)}")
    print(f"  seed accuracy     {_pct(summary.seed_accuracy)}")
    s, loose = summary.strict, summary.lenient
    print(f"  constraints F1    {_pct(s.f1)}  (P {_pct(s.precision)}, R {_pct(s.recall)})")
    print(f"  ignoring strength {_pct(loose.f1)}")
    print(f"  keep recall       {_pct(summary.keep_recall)}")
    print(f"  negation leaks    {_pct(summary.leak_rate)} of queries with negated words")
    print(f"\n  {'field':26} {'P':>7} {'R':>7} {'F1':>7} {'gold':>5}")
    for name, c in sorted(summary.per_field.items(), key=lambda item: -(item[1].tp + item[1].fn)):
        precision = _pct(c.precision) if c.tp + c.fp else "   n/a"  # never predicted
        print(f"  {name:26} {precision:>7} {_pct(c.recall):>7} {_pct(c.f1):>7} {c.tp + c.fn:5}")
    print(f"\n  {'category':18} {'n':>3} {'exact':>7} {'intent':>7}")
    for category, row in summary.per_category.items():
        print(
            f"  {category:18} {row['n']:3} {_pct(row['exact_match']):>7} "
            f"{_pct(row['intent_accuracy']):>7}"
        )
    if args.errors or args.only:
        _print_errors(results, {g.id: g.text for g in golds})
    if out:
        print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
