"""Open Library lookups by ISBN, with an on-disk cache.

An ISBN lookup touches three record types: the edition (`/isbn/{isbn}.json`), its work
(description, subjects) and each author (name). Every response, including misses, is cached on
disk, so re-running an import never re-fetches. Requests are spaced out to be polite.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2

from shelfwise import __version__
from shelfwise.ingest.normalize import normalize_text, split_title
from shelfwise.ingest.records import MAX_PAGES, MIN_PAGES, EditionRecord

BASE_URL = "https://openlibrary.org"
USER_AGENT = f"Shelfwise/{__version__} (library search portfolio project)"

Json = dict[str, Any]
Fetch = Callable[[str], Json | None]

# MARC language codes seen on Open Library editions -> ISO 639-1.
_LANGUAGES = {
    "eng": "en", "spa": "es", "fre": "fr", "ger": "de", "ita": "it", "por": "pt",
    "dut": "nl", "rus": "ru", "jpn": "ja", "chi": "zh", "ara": "ar", "urd": "ur",
}  # fmt: skip
_YEAR = re.compile(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)")
_SOURCE_REFS = re.compile(r"\(\[source\]\[\d+\]\)|\[\d+\]:\s*\S+")


def http_fetch(timeout: float = 20.0, retries: int = 3) -> Fetch:
    """Fetch JSON over HTTP; 404 means "not found" and returns None."""
    client = httpx2.Client(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )

    def fetch(path: str) -> Json | None:
        for attempt in range(retries):
            try:
                response = client.get(path)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
            except (httpx2.TransportError, httpx2.HTTPStatusError):
                if attempt == retries - 1:
                    raise
                time.sleep(2**attempt)
        return None

    return fetch


def parse_year(value: str | None) -> int | None:
    match = _YEAR.search(value or "")
    return int(match.group(1)) if match else None


def clean_description(value: str | Json | None) -> str | None:
    """Descriptions are a string or {"type": "/type/text", "value": ...}; strip source links."""
    text = value.get("value") if isinstance(value, dict) else value
    if not text:
        return None
    text = text.split("\n----")[0]
    text = _SOURCE_REFS.sub("", text)
    return normalize_text(text) or None


class OpenLibraryClient:
    def __init__(
        self,
        cache_dir: Path,
        fetch: Fetch | None = None,
        min_interval: float = 0.35,
    ) -> None:
        self._cache_dir = cache_dir
        self._fetch = fetch or http_fetch()
        self._min_interval = min_interval
        self._last_request = 0.0
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, path: str) -> Json | None:
        cache_file = self._cache_dir / (hashlib.sha256(path.encode()).hexdigest()[:24] + ".json")
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            return None if cached.get("__missing__") else cached
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        data = self._fetch(path)
        cache_file.write_text(json.dumps(data if data is not None else {"__missing__": True}))
        return data

    def search(self, params: str) -> Json | None:
        return self.get_json(f"/search.json?{params}")

    def _author_name(self, key: str) -> str | None:
        author = self.get_json(f"{key}.json")
        return normalize_text(author["name"]) if author and author.get("name") else None

    def lookup_isbn(self, isbn13: str) -> EditionRecord | None:
        edition = self.get_json(f"/isbn/{isbn13}.json")
        if not edition or not edition.get("title"):
            return None

        work: Json = {}
        work_key = (edition.get("works") or [{}])[0].get("key")
        if work_key:
            work = self.get_json(f"{work_key}.json") or {}

        author_keys = [a["key"] for a in edition.get("authors", []) if "key" in a]
        if not author_keys:
            author_keys = [
                a["author"]["key"] for a in work.get("authors", []) if "key" in a.get("author", {})
            ]
        authors = [name for key in author_keys if (name := self._author_name(key))]

        title, subtitle = split_title(edition["title"], edition.get("subtitle"))
        language_key: str = (edition.get("languages") or [{}])[0].get("key") or "/languages/eng"
        language_code = language_key.rsplit("/", 1)[-1]
        covers = [c for c in work.get("covers", edition.get("covers", [])) if c and c > 0]
        pages = edition.get("number_of_pages")
        pages = pages if isinstance(pages, int) and MIN_PAGES <= pages <= MAX_PAGES else None

        return EditionRecord(
            isbn13=isbn13,
            title=title,
            subtitle=subtitle,
            authors=authors,
            publisher=normalize_text(edition["publishers"][0])
            if edition.get("publishers")
            else None,
            pub_year=parse_year(edition.get("publish_date")),
            first_pub_year=parse_year(work.get("first_publish_date")),
            pages=pages,
            language=_LANGUAGES.get(language_code) or language_code,
            format=edition.get("physical_format"),
            description=clean_description(work.get("description") or edition.get("description")),
            subjects=work.get("subjects", []),
            source_work_key=work_key,
            cover_id=covers[0] if covers else None,
        )
