from shelfwise.ingest.cluster import cluster_editions
from shelfwise.ingest.records import EditionRecord


def edition(isbn: str, title: str, author: str = "Alex Michaelides", **kw: object) -> EditionRecord:
    return EditionRecord(isbn13=isbn, title=title, authors=[author], **kw)  # type: ignore[arg-type]


def test_same_source_work_key_groups_editions() -> None:
    clusters = cluster_editions(
        [
            edition("9781250301697", "The Silent Patient", source_work_key="/works/W1"),
            edition("9781409181620", "Silent Patient", source_work_key="/works/W1"),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].isbns == ["9781250301697", "9781409181620"]


def test_same_title_and_author_groups_across_work_keys() -> None:
    clusters = cluster_editions(
        [
            edition("9781250301697", "The Silent Patient", source_work_key="/works/W1"),
            edition("9781250301710", "The silent patient", source_work_key="/works/W2"),
        ]
    )

    assert len(clusters) == 1


def test_grouping_is_transitive() -> None:
    clusters = cluster_editions(
        [
            edition("9780000000019", "Dune", "Frank Herbert", source_work_key="/works/A"),
            edition("9780000000026", "Dune", "Frank Herbert", source_work_key="/works/B"),
            edition("9780000000033", "Dune (Deluxe)", "Frank Herbert", source_work_key="/works/B"),
        ]
    )

    assert len(clusters) == 1


def test_different_authors_stay_separate() -> None:
    clusters = cluster_editions(
        [
            edition("9780000000019", "Rebecca", "Daphne du Maurier"),
            edition("9780000000026", "Rebecca", "Someone Else"),
        ]
    )

    assert len(clusters) == 2


def test_near_duplicate_titles_are_not_merged() -> None:
    clusters = cluster_editions(
        [
            edition("9780000000019", "The Maidens", source_work_key="/works/A"),
            edition("9780000000026", "The Maidens: A Novel", source_work_key="/works/B"),
        ]
    )

    assert len(clusters) == 2


def test_work_fields_come_from_the_richest_edition() -> None:
    clusters = cluster_editions(
        [
            edition("9780000000019", "Dune", "Frank Herbert", pub_year=2005),
            edition(
                "9780000000026",
                "Dune",
                "Frank Herbert",
                pub_year=1965,
                description="A desert planet.",
                subjects=["Science fiction"],
            ),
        ]
    )

    (cluster,) = clusters
    assert cluster.description == "A desert planet."
    assert cluster.first_pub_year == 1965
    assert cluster.subjects == ["Science fiction"]
