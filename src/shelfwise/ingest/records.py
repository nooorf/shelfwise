from pydantic import BaseModel, Field


class EditionRecord(BaseModel):
    """One edition as delivered by a source, already normalized. Grouped into works later."""

    isbn13: str
    title: str
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    pub_year: int | None = None
    first_pub_year: int | None = None
    pages: int | None = None
    language: str = "en"
    format: str | None = None
    description: str | None = None
    subjects: list[str] = Field(default_factory=list)
    source_work_key: str | None = None  # e.g. Open Library "/works/OL19096402W"
    cover_id: int | None = None
