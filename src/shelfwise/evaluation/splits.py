"""Dev/test split by query family (design doc §27.4).

Deterministic from the family id, so a family's paraphrases always land together and adding new
queries never moves existing ones. About 40% of families go to the locked test split.
"""

import hashlib
from typing import Literal

Split = Literal["dev", "test"]


def split_of(family: str) -> Split:
    bucket = int(hashlib.sha1(family.encode()).hexdigest()[:8], 16) % 5
    return "test" if bucket in (0, 1) else "dev"
