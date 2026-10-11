"""Choose the landing page's featured shelf and look up each book's Open Library cover.

    uv run python scripts/pick_featured.py              # 48 books into data/seed/featured.csv
    uv run python scripts/pick_featured.py --count 60

The most popular books with a description, at most one per author, no later volumes of a
series ("Vol. 20"), nothing tagged explicit (romance 3), and at most --per-genre books sharing
a first genre, so one genre can't fill the shelf. Only books Open Library has a cover for are
kept. Covers are looked up 50 ISBNs to a request, every edition of a book until one has a cover.
The file can be edited by hand afterwards; the order in it is the order on the shelf.
"""

import argparse
import re
import time
from collections import Counter
from collections.abc import Iterator

from sqlalchemy import text

from shelfwise.catalog.db import make_engine
from shelfwise.catalog.featured import FEATURED, Featured, save_featured
from shelfwise.ingest.openlibrary import http_fetch

BATCH = 50
_LATER_VOLUME = re.compile(r"\b(?:vol\.?|volume|book|#)\s*0*(?:[2-9]|\d{2,})\b", re.IGNORECASE)

_CANDIDATES = text(
    """
    SELECT w.work_id, w.title, w.genres[1] AS genre,
           (SELECT wa.author_id FROM work_author wa WHERE wa.work_id = w.work_id
            ORDER BY wa.position LIMIT 1) AS author_id,
           array_agg(e.isbn13 ORDER BY e.isbn13) FILTER (WHERE e.isbn13 IS NOT NULL) AS isbns
    FROM work w
    JOIN edition e USING (work_id)
    LEFT JOIN work_facets f USING (work_id)
    WHERE NOT w.low_info AND w.description IS NOT NULL AND coalesce(f.romance, 0) < 3
    GROUP BY w.work_id, f.work_id
    ORDER BY w.popularity DESC, w.work_id
    LIMIT :limit
    """
)


def chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def cover_ids(isbns: list[str]) -> dict[str, int]:
    """ISBN -> Open Library cover id, for the ISBNs that have one."""
    fetch = http_fetch()
    found: dict[str, int] = {}
    for batch in chunks(isbns, BATCH):
        keys = ",".join(f"ISBN:{i}" for i in batch)
        data = fetch(f"/api/books?bibkeys={keys}&format=json&jscmd=data") or {}
        for key, record in data.items():
            url = (record.get("cover") or {}).get("medium", "")
            if match := re.search(r"/b/id/(\d+)-", url):
                found[key.removeprefix("ISBN:")] = int(match.group(1))
        time.sleep(1)  # polite
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--count", type=int, default=48)
    parser.add_argument("--per-genre", type=int, default=5)
    parser.add_argument("--pool", type=int, default=400, help="most popular books to consider")
    args = parser.parse_args()

    with make_engine().connect() as conn:
        rows = conn.execute(_CANDIDATES, {"limit": args.pool}).all()

    authors: set[int] = set()
    genres: Counter[str] = Counter()
    picked = []
    for r in rows:
        genre = r.genre or "other"
        if r.author_id in authors or genres[genre] >= args.per_genre:
            continue
        if _LATER_VOLUME.search(r.title):
            continue
        authors.add(r.author_id)
        genres[genre] += 1
        picked.append(r)
        if len(picked) >= args.count * 2:  # spares for books without a cover
            break

    covers = cover_ids([i for r in picked for i in r.isbns])
    featured = []
    for r in picked:
        cover = next((covers[i] for i in r.isbns if i in covers), None)
        if cover is not None:
            featured.append(Featured(work_key=r.isbns[0], cover_id=cover, title=r.title))
        if len(featured) == args.count:
            break

    save_featured(featured, FEATURED)
    print(f"{len(featured)} books with covers ({len(picked)} considered) -> {FEATURED}")
    print("first genres:", dict(Counter(r.genre or "other" for r in picked[: len(featured)])))


if __name__ == "__main__":
    main()
