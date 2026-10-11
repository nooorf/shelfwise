"""The GPU day in one command (Phase 7): train, embed, evaluate, and run the locked test split.

On the Mac, the day before:   make gpu-pack          # shelfwise.dump: the catalog, tags, embeddings
On the GPU machine:           make gpu-day DUMP=shelfwise.dump
Afterwards, on the Mac:       make gpu-unpack        # models and reports from gpu-day-results.tar.gz

Steps, in order; each one is recorded in checkpoints/gpu-day/state.json when it finishes, so a
re-run (after a crash, a reboot, a full disk) carries on from the first unfinished step:

  check       CUDA visible to torch, the database up, Ollama answering (the test split's parses)
  restore     load DUMP into an empty database (skipped when the catalog is already there)
  embed-base  bge-base embeddings for any book missing one (the training set's negatives)
  data        the full training set (graded dev queries + synthetic requests)
  embedder    bge-base -> models/bge-base-ft: cached MNRL, batch 256 in mini-batches of 32
  rerankers   bge-base and MiniLM cross-encoders -> models/<base>-rerank-ft
  embed-ft    bge-base-ft embeddings for the whole catalog
  dev-eval    `make eval` on dev: the base setup, then the fine-tuned embedder with each reranker
  sweep       rerank depth sweep for each fine-tuned reranker
  test        the locked test split, ONCE: the base setup and the final one (the fine-tuned
              reranker best on dev, at its best depth). Never repeated, even with --from
  pack        gpu-day-results.tar.gz: the fine-tuned models, the new reports, the LLM cache

Everything is logged to checkpoints/gpu-day/log.txt. `--from <step>` re-runs from a step (not
the test split once it has run); `--dry-run` prints the commands.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path("checkpoints/gpu-day")
STATE = HERE / "state.json"
LOG = HERE / "log.txt"
DATA = Path("data/processed/training")
RESULTS = Path("gpu-day-results.tar.gz")

BASE_EMBEDDER = "bge-base"
BASE_RERANKER = "minilm"  # the off-the-shelf reranker the dev numbers so far used
DEFAULT_DEPTH = 50
FT_RERANKERS = {"bge-base": "bge-base-ft", "minilm": "minilm-ft"}  # base -> its fine-tuned name
NEAR_BEST = 0.005  # a shallower depth within this nDCG@10 of the best wins: it's faster

STEPS = [
    "check", "restore", "embed-base", "data", "embedder", "rerankers",
    "embed-ft", "dev-eval", "sweep", "test", "pack",
]  # fmt: skip

PY = ["uv", "run", "python"]
TRAIN = ["uv", "run", "--group", "train", "python"]


class Day:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.state: dict = json.loads(STATE.read_text()) if STATE.exists() else {"done": []}

    def save(self) -> None:
        STATE.write_text(json.dumps(self.state, indent=1))

    def log(self, line: str) -> None:
        stamped = f"[{datetime.now():%H:%M:%S}] {line}"
        print(stamped, flush=True)
        with LOG.open("a") as f:
            f.write(stamped + "\n")

    def run(self, cmd: list[str], stdin: Path | None = None) -> str:
        """Runs `cmd`, echoing and logging its output; fails the day if it fails."""
        self.log("$ " + " ".join(cmd))
        if self.dry_run:
            return ""
        lines: list[str] = []
        with (
            stdin.open("rb") if stdin else open("/dev/null", "rb") as source,
            LOG.open("a") as log,
            subprocess.Popen(
                cmd, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            ) as proc,
        ):
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                log.write(line)
                lines.append(line)
        if proc.returncode != 0:
            raise SystemExit(f"failed ({proc.returncode}): {' '.join(cmd)}; see {LOG}")
        return "".join(lines)

    def report(self, cmd: list[str]) -> str:
        """Runs an evaluation and returns the report it saved (its last 'report: <path>' line)."""
        out = self.run(cmd)
        if self.dry_run:
            return "<report>"
        found = [ln.split("report:", 1)[1].strip() for ln in out.splitlines() if "report:" in ln]
        if not found:
            raise SystemExit(f"no report path in the output of {' '.join(cmd)}")
        return found[-1]


def steps_per_epoch(file: Path, batch: int) -> int:
    if not file.exists():
        return 40  # a dry run, before the training set exists
    with file.open() as f:
        return max(1, sum(1 for _ in f) // batch)


def check(day: Day, args: argparse.Namespace) -> None:
    probe = "import torch; assert torch.cuda.is_available(), 'no CUDA'; print(torch.cuda.get_device_name(0))"
    day.run(["uv", "sync", "--group", "train"])
    day.run([*TRAIN, "-c", probe])
    day.run(["docker", "compose", "up", "-d", "--wait"])
    day.run(["uv", "run", "alembic", "upgrade", "head"])
    ollama = "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/tags', timeout=5)"
    try:
        day.run([*PY, "-c", ollama])
    except SystemExit:
        day.log("Ollama isn't answering: start `ollama serve` (and `ollama pull qwen3:4b`) before")
        day.log("the test step, or its parsed_hybrid falls back to the rules for uncached queries.")
        if not args.no_llm:
            raise


def restore(day: Day, args: argparse.Namespace) -> None:
    in_db = ["docker", "compose", "exec", "-T", "postgres"]
    reset = [*in_db, "psql", "-U", "shelfwise", "-d", "shelfwise", "-v", "ON_ERROR_STOP=1",
             "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"]  # fmt: skip
    restore_cmd = [*in_db, "pg_restore", "-U", "shelfwise", "-d", "shelfwise", "--no-owner"]
    migrate = ["uv", "run", "alembic", "upgrade", "head"]  # in case the dump is older than the code
    if day.dry_run:
        for cmd in (reset, restore_cmd, migrate):
            day.run(cmd)
        return
    count = "from sqlalchemy import text; from shelfwise.catalog.db import make_engine; e = make_engine(); print(e.connect().execute(text('select count(*) from work')).scalar())"
    out = day.run([*PY, "-c", count]).strip().splitlines()
    works = int(out[-1]) if out and out[-1].isdigit() else 0
    if works > 0:
        day.log(f"the catalog is already here ({works} works): nothing to restore")
        return
    if args.dump is None:
        raise SystemExit(
            "the database is empty: pass DUMP=shelfwise.dump (make gpu-pack on the Mac)"
        )
    day.run(reset)  # the empty tables `check` migrated, so the dump restores without clashes
    day.run(restore_cmd, args.dump)
    day.run(migrate)


def embed_base(day: Day, _: argparse.Namespace) -> None:
    day.run([*PY, "scripts/embed.py", "--model", BASE_EMBEDDER])


def data(day: Day, _: argparse.Namespace) -> None:
    day.run([*TRAIN, "scripts/build_training_set.py"])


def embedder(day: Day, args: argparse.Namespace) -> None:
    batch = args.embedder_batch
    every = max(10, steps_per_epoch(DATA / "embedder_train.jsonl", batch) // 4)
    day.run([
        *TRAIN, "scripts/train_embedder.py", "--base", BASE_EMBEDDER,
        "--batch-size", str(batch), "--mini-batch", "32", "--epochs", str(args.embedder_epochs),
        "--eval-steps", str(every),
    ])  # fmt: skip


def rerankers(day: Day, args: argparse.Namespace) -> None:
    for base, batch in (("bge-base", 32), ("minilm", 64)):
        every = max(10, steps_per_epoch(DATA / "reranker_train.jsonl", batch) // 4)
        day.run([
            *TRAIN, "scripts/train_reranker.py", "--base", base, "--batch-size", str(batch),
            "--epochs", str(args.reranker_epochs), "--eval-steps", str(every),
        ])  # fmt: skip


def embed_ft(day: Day, _: argparse.Namespace) -> None:
    day.run([*PY, "scripts/embed.py", "--model", f"{BASE_EMBEDDER}-ft"])


def evaluate(embedding: str, reranker: str, split: str = "dev", depth: int | None = None):
    cmd = [*PY, "scripts/evaluate.py", "--split", split, "--embedding-model", embedding,
           "--reranker", reranker, "--parser", "cascade"]  # fmt: skip
    return cmd + (["--rerank-depth", str(depth)] if depth else [])


def dev_eval(day: Day, _: argparse.Namespace) -> None:
    reports = {"base": day.report(evaluate(BASE_EMBEDDER, BASE_RERANKER))}
    for name in FT_RERANKERS.values():
        reports[name] = day.report(evaluate(f"{BASE_EMBEDDER}-ft", name))
    day.state["dev"] = reports


def sweep(day: Day, _: argparse.Namespace) -> None:
    reports = {}
    for name in FT_RERANKERS.values():
        reports[name] = day.report([
            *PY, "scripts/sweep.py", "--embedding-model", f"{BASE_EMBEDDER}-ft",
            "depth", "--reranker", name,
        ])  # fmt: skip
    day.state["sweep"] = reports


def final_setup(day: Day) -> tuple[str, int]:
    """The fine-tuned reranker with the best hybrid_rerank on dev, and its depth: the shallowest
    within NEAR_BEST of its sweep's best."""
    scores = {
        name: json.loads(Path(day.state["dev"][name]).read_text())["systems"]["hybrid_rerank"][
            "overall"
        ]["ndcg@10"]["mean"]
        for name in FT_RERANKERS.values()
    }
    best = max(scores, key=lambda n: scores[n])
    rows = json.loads(Path(day.state["sweep"][best]).read_text())["rows"]
    top = max(r["ndcg@10"] for r in rows)
    depth = min(r["depth"] for r in rows if r["ndcg@10"] >= top - NEAR_BEST)
    day.log(f"final: {best} at depth {depth} (dev hybrid_rerank nDCG@10 {scores})")
    return best, depth


def test(day: Day, _: argparse.Namespace) -> None:
    if day.dry_run:
        day.run(evaluate(BASE_EMBEDDER, BASE_RERANKER, "test"))
        day.run(evaluate(f"{BASE_EMBEDDER}-ft", "<best-ft>", "test", 0))
        return
    reranker, depth = final_setup(day)
    day.state["final"] = {"embedding": f"{BASE_EMBEDDER}-ft", "reranker": reranker, "depth": depth}
    day.state["test_started"] = True  # the locked split is spent from here on, even on a crash
    day.save()
    day.state["test"] = {
        "base": day.report(evaluate(BASE_EMBEDDER, BASE_RERANKER, "test", DEFAULT_DEPTH)),
        "final": day.report(evaluate(f"{BASE_EMBEDDER}-ft", reranker, "test", depth)),
    }


def pack(day: Day, _: argparse.Namespace) -> None:
    started = day.state.get("started", "")
    models = [Path("models") / f"{BASE_EMBEDDER}-ft"]
    models += [Path("models") / f"{base}-rerank-ft" for base in FT_RERANKERS]
    reports = [p for p in Path("eval/reports").glob("*.json") if p.name >= started]
    day.log(f"packing {len(models)} models and {len(reports)} reports into {RESULTS}")
    if day.dry_run:
        return
    with tarfile.open(RESULTS, "w:gz") as tar:
        for path in [*models, *reports, Path("eval/data/llm_cache.jsonl"), LOG, STATE]:
            if path.exists():
                tar.add(path)
    day.log(f"done: copy {RESULTS} to the Mac and run `make gpu-unpack`")


ACTIONS = {
    "check": check, "restore": restore, "embed-base": embed_base, "data": data,
    "embedder": embedder, "rerankers": rerankers, "embed-ft": embed_ft, "dev-eval": dev_eval,
    "sweep": sweep, "test": test, "pack": pack,
}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dump", type=Path, help="pg_dump from `make gpu-pack`, for an empty DB")
    parser.add_argument("--from", dest="start", choices=STEPS, help="re-run from this step")
    parser.add_argument("--dry-run", action="store_true", help="print the commands only")
    parser.add_argument("--no-llm", action="store_true", help="go on without Ollama")
    parser.add_argument("--embedder-batch", type=int, default=256)
    parser.add_argument("--embedder-epochs", type=float, default=3)
    parser.add_argument("--reranker-epochs", type=float, default=2)
    args = parser.parse_args()

    HERE.mkdir(parents=True, exist_ok=True)
    day = Day(args.dry_run)
    day.state.setdefault("started", f"{datetime.now():%Y%m%d-%H%M%S}")
    if args.start:
        keep = STEPS[: STEPS.index(args.start)]
        day.state["done"] = [s for s in day.state["done"] if s in keep]
    if args.dump and not args.dump.exists():
        raise SystemExit(f"no {args.dump}")
    if shutil.which("uv") is None:
        raise SystemExit("uv isn't installed: https://docs.astral.sh/uv/")

    for step in STEPS:
        if step in day.state["done"]:
            continue
        if step == "test" and day.state.get("test_started"):
            if args.start == "pack":
                continue  # it crashed after starting: pack what it saved
            raise SystemExit(
                "the locked test split already ran once; its reports are in the state file. "
                "Pack with --from pack."
            )
        day.log(f"== {step}")
        clock = time.perf_counter()
        ACTIONS[step](day, args)
        day.log(f"== {step} done in {(time.perf_counter() - clock) / 60:.1f} min")
        if not args.dry_run:
            day.state["done"].append(step)
            day.save()
    day.log("the GPU day is complete")


if __name__ == "__main__":
    main()
