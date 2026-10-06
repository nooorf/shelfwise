"""Build a sample seed list of real ISBNs from Open Library subject searches.

Stand-in for scanning a real shelf: replace data/seed/isbns.csv with your own scans later.

    uv run python scripts/sample_seed_isbns.py --per-subject 15
"""

import argparse
import csv
from pathlib import Path
from urllib.parse import urlencode

from shelfwise.ingest.normalize import normalize_isbn
from shelfwise.ingest.openlibrary import OpenLibraryClient

GENERAL_SUBJECTS = [
    "psychological fiction",
    "thrillers",
    "detective and mystery stories",
    "fantasy",
    "science fiction",
    "love stories",
    "historical fiction",
    "horror tales",
    "young adult fiction",
    "biography",
    "history",
    "self-help techniques",
]
# Course and technical books a university library holds (eval category "learning").
TECHNICAL_SUBJECTS = [
    "computer programming",
    "algorithms",
    "data structures (computer science)",
    "operating systems (computers)",
    "computer networks",
    "database management",
    "machine learning",
    "artificial intelligence",
    "parallel programming (computer science)",
    "computer architecture",
    "distributed systems",
    "software engineering",
    "systems engineering",
    "python (computer program language)",
    "c++ (computer program language)",
    "linear algebra",
    "calculus",
]
DEFAULT_SUBJECTS = GENERAL_SUBJECTS + TECHNICAL_SUBJECTS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subjects", nargs="+", default=DEFAULT_SUBJECTS)
    parser.add_argument("--per-subject", type=int, default=15)
    parser.add_argument("--out", type=Path, default=Path("data/seed/isbns.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/openlibrary"))
    args = parser.parse_args()

    client = OpenLibraryClient(args.cache_dir)
    seen_works: set[str] = set()
    rows: list[dict[str, str]] = []
    for subject in args.subjects:
        params = urlencode(
            {
                "subject": subject,
                "language": "eng",
                "fields": "key,title,author_name,isbn",
                "sort": "readinglog",
                "limit": args.per_subject * 3,
            }
        )
        docs = (client.search(params) or {}).get("docs", [])
        picked = 0
        for doc in docs:
            if picked >= args.per_subject or doc["key"] in seen_works:
                continue
            # Prefer ISBN-13s in the English-language registration groups (978-0, 978-1).
            isbns = [n for raw in doc.get("isbn", []) if (n := normalize_isbn(raw)) and raw == n]
            isbn13 = next((n for n in isbns if n.startswith(("9780", "9781"))), None)
            if not isbn13:
                continue
            seen_works.add(doc["key"])
            rows.append(
                {
                    "isbn13": isbn13,
                    "title": doc.get("title", ""),
                    "author": ", ".join(doc.get("author_name", [])[:2]),
                    "subject": subject,
                }
            )
            picked += 1
        print(f"{subject:32} {picked:3d} works")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["isbn13", "title", "author", "subject"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} ISBNs to {args.out}")


if __name__ == "__main__":
    main()
