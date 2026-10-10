from pathlib import Path

from shelfwise.evaluation.grounding import (
    Case,
    Outcome,
    Progress,
    affirms,
    case_key,
    kinds,
    load_cases,
    summarize,
)

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


def test_a_denial_excuses_its_own_sentence_only() -> None:
    assert affirms(
        "I couldn't find The Silent Lighthouse. If you loved The Silent Lighthouse, try these.",
        FAKE,
    )
    assert not affirms(
        "I couldn't find The Silent Lighthouse in this library.\nHere are coastal mysteries.", FAKE
    )


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


def test_saved_outcomes_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "progress.jsonl"
    key = case_key(FAKE, "qwen3:8b")
    Progress(path).add(
        Outcome("naive_rag", "N01", "nonexistent", problems={"invented"}, affirmed=True), key
    )

    saved = Progress(path).get("naive_rag", FAKE, key)

    assert saved is not None and saved.problems == {"invented"} and saved.affirmed
    assert Progress(path).get("full", FAKE, key) is None


def test_a_changed_case_model_or_code_is_answered_again(tmp_path: Path) -> None:
    progress = Progress(tmp_path / "progress.jsonl")
    progress.add(Outcome("full", "N01", "nonexistent"), case_key(FAKE, "qwen3:8b", "abc:1"))
    edited = Case(
        id="N01", kind="nonexistent", text="do you have it?", title="The Silent Lighthouse"
    )

    assert progress.get("full", FAKE, case_key(FAKE, "qwen3:8b", "abc:1")) is not None
    assert progress.get("full", FAKE, case_key(FAKE, "qwen3:4b", "abc:1")) is None
    assert progress.get("full", FAKE, case_key(FAKE, "qwen3:8b", "abc:2")) is None
    assert progress.get("full", edited, case_key(edited, "qwen3:8b", "abc:1")) is None


def test_redo_drops_one_system_and_keeps_the_others(tmp_path: Path) -> None:
    path = tmp_path / "progress.jsonl"
    key = case_key(FAKE, "qwen3:8b")
    progress = Progress(path)
    for system in ("full", "naive_rag", "llm_only"):
        progress.add(Outcome(system, "N01", "nonexistent"), key)

    assert progress.forget(["full"]) == 1

    reloaded = Progress(path)
    assert reloaded.get("full", FAKE, key) is None
    assert reloaded.get("naive_rag", FAKE, key) is not None
    assert reloaded.get("llm_only", FAKE, key) is not None
