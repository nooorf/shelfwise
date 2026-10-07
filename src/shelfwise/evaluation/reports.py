"""Where evaluation reports go, and which code version produced them."""

import subprocess
from datetime import datetime
from pathlib import Path

REPORTS = Path("eval/reports")


def git_version() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


def report_path(git: str, suffix: str) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    return REPORTS / f"{datetime.now():%Y%m%d-%H%M%S}_{git}_{suffix}.json"
