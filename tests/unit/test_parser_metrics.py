import pytest

from shelfwise.evaluation.parser_gold import GoldParse, parse_constraint
from shelfwise.evaluation.parser_metrics import (
    match_constraints,
    mentions,
    score_query,
    summarize,
)
from shelfwise.query.constraints import Constraint
from shelfwise.query.request import LookupSpec, ParsedRequest


def gold(**fields: object) -> GoldParse:
    base: dict = {
        "id": "Q1",
        "text": "query",
        "category": "multi_constraint",
        "family": "Q1",
        "source": "llm-draft",
        "intent": "discover",
    }
    specs = fields.pop("constraints", [])
    return GoldParse(**{**base, **fields}, constraints=tuple(map(parse_constraint, specs)))  # type: ignore[arg-type]


def constraint(spec: str) -> Constraint:
    c = parse_constraint(spec)
    return Constraint.model_validate({**vars(c), "source": "llm"})


def request(*specs: str, **fields: object) -> ParsedRequest:
    fields.setdefault("intent", "discover")
    return ParsedRequest(constraints=[constraint(s) for s in specs], **fields)  # type: ignore[arg-type]


def test_mystery_under_300_pages_after_2015_by_hand() -> None:
    g = gold(
        constraints=["genre in [mystery] soft", "pages lt 300 hard", "year gt 2015 hard"],
        keep=("mystery",),
    )
    predicted = request(
        "pages lt 300 hard",
        "year gt 2015 soft",  # right filter, wrong strength
        "facet.darkness gte 2 soft",  # invented
        semantic_query="mysteries",
    )

    result = score_query(g, predicted)

    assert [str(c) for c in result.matched] == ["pages lt 300 hard"]
    assert sorted(map(str, result.missing)) == ["genre in [mystery] soft", "year gt 2015 hard"]
    assert sorted(map(str, result.extra)) == ["facet.darkness gte 2 soft", "year gt 2015 soft"]
    assert (result.lenient.tp, result.lenient.fp, result.lenient.fn) == (2, 1, 1)
    assert result.keep_found == 1  # plural counts
    assert not result.exact

    summary = summarize([result])
    assert summary.strict.precision == pytest.approx(1 / 3)
    assert summary.strict.recall == pytest.approx(1 / 3)
    assert summary.lenient.f1 == pytest.approx(2 / 3)
    assert summary.per_field["year"].fp == 1
    assert summary.per_field["year"].fn == 1
    assert summary.per_field["genre"].fn == 1


def test_exact_match_needs_intent_lookup_and_every_constraint() -> None:
    g = gold(intent="lookup", title="Murder on the Orient Express", constraints=[])

    right = request(intent="lookup", lookup=LookupSpec(title="Murder on the Orient Express"))
    typo = request(intent="lookup", lookup=LookupSpec(title="murder on the orient expres"))
    wrong_book = request(intent="lookup", lookup=LookupSpec(title="Death on the Nile"))
    with_filter = request("available_now eq true hard", intent="lookup", lookup=right.lookup)

    assert score_query(g, right).exact
    assert score_query(g, typo).exact  # titles compare fuzzily
    assert not score_query(g, wrong_book).exact
    assert not score_query(g, with_filter).exact
    assert not score_query(g, request(intent="discover", lookup=right.lookup)).exact


def test_title_alternatives_and_series_suffixes() -> None:
    g = gold(intent="similar", seeds=("Nineteen Eighty-Four | 1984",))

    assert score_query(g, request(intent="similar", seed_titles=["1984"])).seeds_ok
    assert score_query(g, request(intent="similar", seed_titles=["Nineteen Eighty-Four"])).seeds_ok
    assert not score_query(
        g, request(intent="similar", seed_titles=["1984", "Animal Farm"])
    ).seeds_ok
    hp = gold(intent="similar", seeds=("Harry Potter and the Half-Blood Prince",))
    linked = request(
        intent="similar", seed_titles=["Harry Potter and the Half-Blood Prince (Harry Potter, #6)"]
    )
    assert score_query(hp, linked).seeds_ok


def test_value_comparison() -> None:
    def same(gold_spec: str, predicted_spec: str) -> bool:
        matched, _, _ = match_constraints(
            [parse_constraint(gold_spec)], [parse_constraint(predicted_spec)]
        )
        return bool(matched)

    assert same("genre in [mystery, thriller] soft", "genre in [thriller, mystery] soft")
    assert same("not theme eq space soft", "not theme eq outer space soft")
    assert same("not theme eq dog dies | death of a dog soft", "not theme eq death of a dog soft")
    assert not same("not theme eq space soft", "theme eq space soft")  # polarity matters
    assert not same("facet.romance eq 0 hard", "facet.romance lte 1 hard")
    assert not same("facet.fiction eq true soft", "facet.darkness eq 1 soft")


def test_negation_leaks_and_keep_phrases() -> None:
    g = gold(
        constraints=["not facet.supernatural eq yes hard"],
        keep=("psychological",),
        drop=("supernatural",),
    )

    leaky = score_query(g, request(semantic_query="psychological nothing supernatural"))
    clean = score_query(g, request(semantic_query="psychological"))

    assert leaky.leaked == ["supernatural"]
    assert clean.leaked == []
    assert summarize([leaky, clean]).leak_rate == 0.5
    assert mentions("science fiction about space", "sci fi | science fiction")
    assert not mentions("warm stories", "war")  # whole words only


def test_accuracies_only_count_queries_that_need_them() -> None:
    lookup = score_query(
        gold(intent="lookup", author="Stephen King"),
        request(intent="lookup", lookup=LookupSpec(author="stephen king")),
    )
    plain = score_query(gold(), request())

    summary = summarize([lookup, plain])

    assert summary.lookup_accuracy == 1.0
    assert summary.seed_accuracy is None
    assert summary.exact_match == 1.0
    assert summary.leak_rate is None
