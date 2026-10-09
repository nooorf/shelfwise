from pathlib import Path

from shelfwise.evaluation.grounding import Case, Outcome, affirms, kinds, load_cases, summarize

FAKE = Case(id="N01", kind="nonexistent", text="do you have it", title="The Silent Lighthouse",
            author="Mara Quill")  # fmt: skip


def test_set_e_loads_with_unique_ids() -> None:
    cases, generated = load_cases(Path("eval/data/grounding.yaml"))
    by_kind = {
        k: sum(c.kind == k for c in cases)
        for k in ("nonexistent", "injection", "catalog_injection")
    }
    assert by_kind == {"nonexistent": 30, "injection": 20, "catalog_injection": 5}
    assert generated == {"borrowed": 25, "discovery": 70}
    assert all(c.title or c.author for c in cases if c.kind == "nonexistent")


def test_validator_messages_become_kinds() -> None:
    assert kinds([
        "names a title that wasn't given: 'gone girl'",
        "3: talks about availability: 'on the shelf'",
        "intro: a claim the record doesn't make: 'bestseller'",
        "llm: Ollama not reachable",
    ]) == {"invented", "availability", "claim"}  # fmt: skip


def test_mentioning_a_made_up_book_counts_unless_it_is_denied() -> None:
    assert affirms("The Silent Lighthouse is a moody coastal mystery.", FAKE)
    assert affirms("Mara Quill writes beautifully.", FAKE)
    assert not affirms("I couldn't find The Silent Lighthouse, but these are close.", FAKE)
    assert not affirms("Here are some coastal mysteries.", FAKE)


def test_summary_rates_per_system_and_kind() -> None:
    outcomes = [
        Outcome("full", "N01", "nonexistent", raw={"invented"}, fallback=True),
        Outcome("full", "D01", "discovery"),
        Outcome(
            "llm_only",
            "N01",
            "nonexistent",
            problems={"availability"},
            affirmed=True,
            suggested=5,
            unowned=4,
        ),
        Outcome("llm_only", "D01", "discovery", suggested=5, unowned=1),
        Outcome("llm_only", "D02", "discovery", error="timeout"),
    ]
    report = summarize(outcomes)

    full = report["full"]["overall"]
    assert (full["n"], full["invented"], full["raw_invented"], full["fallback"]) == (2, 0, 0.5, 0.5)
    llm = report["llm_only"]
    assert (llm["overall"]["n"], llm["overall"]["errors"]) == (2, 1)
    assert llm["overall"]["unowned_share"] == 0.5 and llm["nonexistent"]["affirmed"] == 1.0
    assert llm["overall"]["availability"] == 0.5
