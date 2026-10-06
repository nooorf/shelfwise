"""Give every book shelf locations, copies and a year of simulated circulation.

    uv run python scripts/simulate_library.py            # today, seed 7
    uv run python scripts/simulate_library.py --seed 3 --today 2026-10-06

Replaces all existing copies and loans. Deterministic for a given seed and date.
"""

import argparse
from datetime import date

from shelfwise.catalog.circulation import populate_library
from shelfwise.catalog.db import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    with make_engine().begin() as conn:
        stats = populate_library(conn, today=args.today, seed=args.seed)
    print(
        f"{stats.works} works -> {stats.copies} copies, {stats.loans} loans over 12 months, "
        f"{stats.on_loan_now} copies on loan today ({stats.on_loan_now / max(stats.copies, 1):.0%})"
    )


if __name__ == "__main__":
    main()
