"""Keep availability changing during a demo: a few returns and checkouts every interval.

    uv run python scripts/availability_tick.py --interval 60 --events 3

Stop with Ctrl-C.
"""

import argparse
import random
import time
from datetime import UTC, datetime

from shelfwise.catalog.circulation import tick
from shelfwise.catalog.db import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between ticks")
    parser.add_argument("--events", type=int, default=3, help="returns/checkouts per tick")
    parser.add_argument("--once", action="store_true", help="run a single tick and exit")
    args = parser.parse_args()

    engine = make_engine()
    rng = random.Random()
    while True:
        with engine.begin() as conn:
            for line in tick(conn, rng, datetime.now(UTC), events=args.events):
                print(f"{datetime.now():%H:%M:%S} {line}")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
