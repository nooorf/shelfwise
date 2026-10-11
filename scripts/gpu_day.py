"""The GPU day in one command, run from the Mac (Phase 7): only the training goes to the GPU.

    make gpu-day HOST=you@gpu-box                     # over SSH (Tailscale), the real run
    make gpu-day HOST=you@gpu-box ARGS=--dry-run      # print every command, run nothing
    make gpu-day HOST=local ARGS=--smoke              # rehearse it all on the Mac, tiny training

The GPU machine needs only an NVIDIA driver, SSH and internet (for uv, PyTorch and the three
base models from Hugging Face); uv is installed there if missing. No repo, database, Docker or
Ollama: a folder with the package, the two trainers and the training data is copied over
(~/shelfwise-gpu), trained there, and the models are copied back. Everything else runs here,
next to the database and the LLM cache. Steps, in order, each recorded in
checkpoints/gpu-day/state.json when it finishes, so a re-run carries on from the first
unfinished one:

  check      database up, Ollama answering (the test split's parses); the GPU over SSH, uv there
  data       bge-base embeddings for any new book, then the full training set (a few MB)
  push       the training folder to the GPU machine (rsync)
  train      on the GPU, in the background (an SSH drop doesn't stop it; a re-run reattaches):
             bge-base -> bge-base-ft embedder (cached MNRL, batch 256 in mini-batches of 32),
             then the bge-base and MiniLM rerankers; each model it already finished is skipped
  pull       the three models back into models/
  embed-ft   bge-base-ft embeddings for the whole catalog
  dev-eval   the dev benchmark: the base setup, then the fine-tuned embedder with each reranker
  sweep      rerank depth sweep for each fine-tuned reranker
  test       the locked test split, ONCE: the base setup and the final one (the fine-tuned
             reranker best on dev, at its best depth). Never repeated, even with --from

Logged to checkpoints/gpu-day/log.txt. `--from <step>` re-runs from a step (not the test split
once it has run).
"""

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path("checkpoints/gpu-day")
STATE = HERE / "state.json"
LOG = HERE / "log.txt"
DATA = Path("data/processed/training")
REMOTE_DIR = "shelfwise-gpu"  # on the GPU machine, under its home directory
POLL_S = 30

BASE_EMBEDDER = "bge-base"
BASE_RERANKER = "minilm"  # the off-the-shelf reranker the dev numbers so far used
DEFAULT_DEPTH = 50
RERANKER_BATCH = {"bge-base": 32, "minilm": 64}  # the rerankers to fine-tune, by base
NEAR_BEST = 0.005  # a shallower depth within this nDCG@10 of the best wins: it's faster

# What the GPU machine gets: enough to `uv sync` the package and run the two trainers.
PUSHED = ["pyproject.toml", "uv.lock", ".python-version", "README.md", "src",
          "scripts/train_embedder.py", "scripts/train_reranker.py", str(DATA)]  # fmt: skip

STEPS = ["check", "data", "push", "train", "pull", "embed-ft", "dev-eval", "sweep", "test"]

PY = ["uv", "run", "python"]
TRAIN = ["uv", "run", "--group", "train", "python"]
CUDA = "import torch; assert torch.cuda.is_available(), 'no CUDA'; print(torch.cuda.get_device_name(0))"


class Day:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dry_run: bool = args.dry_run
        self.local = args.host == "local"  # the "GPU machine" is a folder on this Mac
        default_dir = str((HERE / "remote").resolve()) if self.local else REMOTE_DIR
        self.remote_dir: str = args.remote_dir or default_dir
        self.state: dict = json.loads(STATE.read_text()) if STATE.exists() else {"done": []}
        self.rerankers: list[str] = args.rerankers  # bases, e.g. ["bge-base", "minilm"]

    @property
    def fine_tuned(self) -> list[str]:
        """The fine-tuned rerankers' names (ranking/rerank.py): bge-base-ft, minilm-ft."""
        return [f"{base}-ft" for base in self.rerankers]

    @property
    def model_dirs(self) -> list[str]:
        return [f"{BASE_EMBEDDER}-ft", *(f"{base}-rerank-ft" for base in self.rerankers)]

    def save(self) -> None:
        STATE.write_text(json.dumps(self.state, indent=1))

    def log(self, line: str) -> None:
        stamped = f"[{datetime.now():%H:%M:%S}] {line}"
        print(stamped, flush=True)
        with LOG.open("a") as f:
            f.write(stamped + "\n")

    def run(self, cmd: list[str], quiet: bool = False) -> str:
        """Runs `cmd` here, echoing and logging its output; fails the day if it fails."""
        self.log("$ " + shlex.join(cmd))
        if self.dry_run:
            return ""
        lines: list[str] = []
        with (
            LOG.open("a") as log,
            subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
            ) as proc,
        ):  # fmt: skip
            assert proc.stdout is not None
            for line in proc.stdout:
                if not quiet:
                    sys.stdout.write(line)
                log.write(line)
                lines.append(line)
        if proc.returncode != 0:
            raise SystemExit(f"failed ({proc.returncode}): {shlex.join(cmd)}; see {LOG}")
        return "".join(lines)

    def on_gpu(self, script: str) -> list[str]:
        """A shell command for the GPU machine: over SSH, or in bash for a local rehearsal."""
        return ["bash", "-c", script] if self.local else ["ssh", self.args.host, script]

    def target(self, path: str = "") -> str:
        """An rsync destination or source on the GPU machine."""
        where = f"{self.remote_dir}/{path}"
        return where if self.local else f"{self.args.host}:{where}"

    def report(self, cmd: list[str]) -> str:
        """Runs an evaluation and returns the report it saved (its last 'report: <path>' line)."""
        out = self.run(cmd)
        if self.dry_run:
            return "<report>"
        found = [ln.split("report:", 1)[1].strip() for ln in out.splitlines() if "report:" in ln]
        if not found:
            raise SystemExit(f"no report path in the output of {shlex.join(cmd)}")
        return found[-1]


def check(day: Day) -> None:
    day.run(["docker", "compose", "up", "-d", "--wait"])
    day.run(["uv", "run", "alembic", "upgrade", "head"])
    ollama = "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/tags')"
    try:
        day.run([*PY, "-c", ollama], quiet=True)
    except SystemExit:
        if not day.args.no_llm:
            raise SystemExit(
                "Ollama isn't answering: run `make llm` in another terminal (the test split's "
                "requests aren't in the LLM cache yet), or pass --no-llm to go on without it."
            ) from None
    if not day.local:
        day.run(day.on_gpu("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"))
        uv = 'export PATH="$HOME/.local/bin:$PATH"; command -v uv >/dev/null || '
        uv += "curl -LsSf https://astral.sh/uv/install.sh | sh; uv --version"
        day.run(day.on_gpu(uv))


def data(day: Day) -> None:
    day.run([*PY, "scripts/embed.py", "--model", BASE_EMBEDDER])
    subset = ["--subset", "0.02"] if day.args.smoke else []
    day.run([*TRAIN, "scripts/build_training_set.py", *subset])


def push(day: Day) -> None:
    day.run(day.on_gpu(f"mkdir -p {shlex.quote(day.remote_dir)}"))
    day.run([
        "rsync", "-az", "--relative", "--exclude", "__pycache__", *PUSHED, day.target(),
    ])  # fmt: skip


def steps_per_epoch(file: Path, batch: int) -> int:
    if not file.exists():
        return 40  # a dry run, before the training set exists
    with file.open() as f:
        return max(1, sum(1 for _ in f) // batch)


def training_script(day: Day) -> str:
    """What runs on the GPU machine, in the background: sync, check CUDA, then train each model
    it doesn't have yet. The `status` file says running, done or failed (and where)."""
    a = day.args
    smoke = ["--max-steps", "3"] if a.smoke else []
    every = max(10, steps_per_epoch(DATA / "embedder_train.jsonl", a.embedder_batch) // 4)
    embedder = [
        "scripts/train_embedder.py", "--base", BASE_EMBEDDER,
        "--batch-size", str(8 if a.smoke else a.embedder_batch),
        # The cached loss re-runs the model with dropout, which MPS can't: plain loss on a Mac.
        "--mini-batch", str(0 if day.local else 32), "--epochs", str(a.embedder_epochs),
        "--eval-steps", str(3 if a.smoke else every), *smoke,
    ]  # fmt: skip
    jobs = [("embedder", f"models/{BASE_EMBEDDER}-ft", embedder)]
    for base in day.rerankers:
        batch = RERANKER_BATCH[base]
        every = max(10, steps_per_epoch(DATA / "reranker_train.jsonl", batch) // 4)
        jobs.append((f"reranker-{base}", f"models/{base}-rerank-ft", [
            "scripts/train_reranker.py", "--base", base,
            "--batch-size", str(8 if a.smoke else batch), "--epochs", str(a.reranker_epochs),
            "--eval-steps", str(3 if a.smoke else every), *smoke,
        ]))  # fmt: skip
    lines = [
        "set -euo pipefail",
        f"cd {shlex.quote(day.remote_dir)}",
        'export PATH="$HOME/.local/bin:$PATH"',
        "step=start",
        """trap 'echo "failed: $step" > status' ERR""",
        "step=sync; uv sync --group train",
    ]
    if not day.local:
        lines.append(f"step=cuda; uv run --group train python -c {shlex.quote(CUDA)}")
    for name, out, cmd in jobs:
        run = shlex.join(["uv", "run", "--group", "train", "python", *cmd])
        lines.append(f"step={name}; [ -f {out}/shelfwise_training.json ] || {run}")
    lines.append("echo done > status")
    return "\n".join(lines) + "\n"


def train(day: Day) -> None:
    folder = shlex.quote(day.remote_dir)
    if day.dry_run:
        day.log("training script for the GPU machine:\n" + training_script(day))
        return
    status = day.run(day.on_gpu(f"cat {folder}/status 2>/dev/null || true"), quiet=True).strip()
    if status == "running":
        day.log("training is already running on the GPU machine: following it")
    elif status != "done":
        script = shlex.quote(training_script(day))
        start = (
            f"cd {folder} && printf %s {script} > train.sh && : > train.log && "
            "echo running > status && (nohup bash train.sh >> train.log 2>&1 < /dev/null &)"
        )
        day.run(day.on_gpu(start))
    seen = 0
    while True:
        poll = f"cd {folder} && cat status && echo ---- && tail -c +{seen + 1} train.log"
        try:
            out = subprocess.run(
                day.on_gpu(poll), capture_output=True, check=True, timeout=60
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            day.log(f"couldn't reach the GPU machine ({exc}); training goes on there, retrying")
            time.sleep(POLL_S)
            continue
        head, _, new = out.partition(b"----\n")
        seen += len(new)
        text = new.decode("utf-8", "replace")
        sys.stdout.write(text)
        with LOG.open("a") as f:
            f.write(text)
        status = head.decode().strip()
        if status == "done":
            day.log("training finished on the GPU machine")
            return
        if status.startswith("failed"):
            raise SystemExit(
                f"training {status} on the GPU machine (the log is above and in {LOG}); fix it "
                "and run the same command again: models already finished are kept"
            )
        time.sleep(POLL_S)


def pull(day: Day) -> None:
    Path("models").mkdir(exist_ok=True)
    for name in day.model_dirs:
        day.run(["rsync", "-az", "--delete", day.target(f"models/{name}"), "models/"])


FORGET_FT = (
    "from sqlalchemy import text; from shelfwise.catalog.db import make_engine\n"
    "with make_engine().begin() as c:\n"
    "    n = c.execute(text(\"DELETE FROM work_embedding WHERE model_name = 'bge-base-ft'\")).rowcount\n"
    "print(f'forgot {n} bge-base-ft embeddings')"
)


def embed_ft(day: Day) -> None:
    # Embeddings are kept per model name and content hash, so ones from an earlier bge-base-ft
    # (another run, a smoke run) would look current: drop them all, embed with the new weights.
    day.run([*PY, "-c", FORGET_FT])
    day.run([*PY, "scripts/embed.py", "--model", f"{BASE_EMBEDDER}-ft"])


def clean_up_smoke(day: Day) -> None:
    """A smoke run's models, embeddings and reports are junk: remove them, so /bench and the
    real run never see them."""
    reports = [*day.state.get("dev", {}).values(), *day.state.get("sweep", {}).values()]
    day.run(["rm", "-rf", *(f"models/{name}" for name in day.model_dirs), *reports])
    day.run([*PY, "-c", FORGET_FT])
    STATE.unlink(missing_ok=True)


def evaluate(embedding: str, reranker: str, split: str = "dev", depth: int | None = None):
    cmd = [*PY, "scripts/evaluate.py", "--split", split, "--embedding-model", embedding,
           "--reranker", reranker, "--parser", "cascade"]  # fmt: skip
    return cmd + (["--rerank-depth", str(depth)] if depth else [])


def dev_eval(day: Day) -> None:
    reports = {"base": day.report(evaluate(BASE_EMBEDDER, BASE_RERANKER))}
    for name in day.fine_tuned:
        reports[name] = day.report(evaluate(f"{BASE_EMBEDDER}-ft", name))
    day.state["dev"] = reports


def sweep(day: Day) -> None:
    reports = {}
    for name in day.fine_tuned:
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
        for name in day.fine_tuned
    }
    best = max(scores, key=lambda n: scores[n])
    rows = json.loads(Path(day.state["sweep"][best]).read_text())["rows"]
    top = max(r["ndcg@10"] for r in rows)
    depth = min(r["depth"] for r in rows if r["ndcg@10"] >= top - NEAR_BEST)
    day.log(f"final: {best} at depth {depth} (dev hybrid_rerank nDCG@10 {scores})")
    return best, depth


def test(day: Day) -> None:
    if day.dry_run:
        day.run(evaluate(BASE_EMBEDDER, BASE_RERANKER, "test", DEFAULT_DEPTH))
        day.run(evaluate(f"{BASE_EMBEDDER}-ft", "<best-ft>", "test", 0))
        return
    if day.args.smoke:
        day.log("smoke run: the locked test split is left alone")
        return
    reranker, depth = final_setup(day)
    day.state["final"] = {"embedding": f"{BASE_EMBEDDER}-ft", "reranker": reranker, "depth": depth}
    day.state["test_started"] = True  # the locked split is spent from here on, even on a crash
    day.save()
    day.state["test"] = {
        "base": day.report(evaluate(BASE_EMBEDDER, BASE_RERANKER, "test", DEFAULT_DEPTH)),
        "final": day.report(evaluate(f"{BASE_EMBEDDER}-ft", reranker, "test", depth)),
    }


ACTIONS = {
    "check": check, "data": data, "push": push, "train": train, "pull": pull,
    "embed-ft": embed_ft, "dev-eval": dev_eval, "sweep": sweep, "test": test,
}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", required=True,
                        help="user@machine for SSH, or 'local' to rehearse on this Mac")  # fmt: skip
    parser.add_argument("--remote-dir", help=f"folder on the GPU machine (default ~/{REMOTE_DIR})")
    parser.add_argument("--from", dest="start", choices=STEPS, help="re-run from this step")
    parser.add_argument("--dry-run", action="store_true", help="print the commands only")
    parser.add_argument("--smoke", action="store_true",
                        help="a rehearsal: 2%% of the data, 3 training steps, no test split")  # fmt: skip
    parser.add_argument("--no-llm", action="store_true", help="go on without Ollama")
    parser.add_argument("--rerankers", nargs="+", choices=list(RERANKER_BATCH),
                        default=list(RERANKER_BATCH), help="which rerankers to fine-tune")  # fmt: skip
    parser.add_argument("--embedder-batch", type=int, default=256)
    parser.add_argument("--embedder-epochs", type=float, default=3)
    parser.add_argument("--reranker-epochs", type=float, default=2)
    args = parser.parse_args()

    HERE.mkdir(parents=True, exist_ok=True)
    if STATE.exists() and json.loads(STATE.read_text()).get("smoke", False) != args.smoke:
        kind = "a smoke run" if args.smoke else "a real run"
        raise SystemExit(f"{STATE} is from the other kind of run: move it away before {kind}")
    day = Day(args)
    day.state["smoke"] = args.smoke
    if args.start:
        keep = STEPS[: STEPS.index(args.start)]
        day.state["done"] = [s for s in day.state["done"] if s in keep]

    for step in STEPS:
        if step in day.state["done"]:
            continue
        if step == "test" and day.state.get("test_started"):
            raise SystemExit(
                "the locked test split already ran once; its reports are in the state file"
            )
        day.log(f"== {step}")
        clock = time.perf_counter()
        ACTIONS[step](day)
        day.log(f"== {step} done in {(time.perf_counter() - clock) / 60:.1f} min")
        if not args.dry_run:
            day.state["done"].append(step)
            day.save()
    if args.smoke and not args.dry_run:
        clean_up_smoke(day)
        day.log("smoke run complete; its models, embeddings and reports are removed")
        return
    day.log("the GPU day is complete")


if __name__ == "__main__":
    main()
