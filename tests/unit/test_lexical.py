import numpy as np
import pytest

from shelfwise.retrieval.lexical import LexicalDoc, LexicalIndex

DOCS = [
    LexicalDoc(1, "Murder on the Orient Express", "Agatha Christie", "detective on a snowy train"),
    LexicalDoc(2, "Train Dreams", "Denis Johnson", "a quiet life; a murder mystery in the woods"),
    LexicalDoc(3, "Cien años de soledad", "Gabriel García Márquez", "magical realism, family saga"),
    LexicalDoc(4, "The Book Thief", "Markus Zusak", "a girl steals books in wartime Germany"),
    LexicalDoc(5, "Data Structures and Algorithms", "Robert Lafore", "trees, graphs, sorting"),
]  # fmt: skip


@pytest.fixture(scope="module")
def index() -> LexicalIndex:
    return LexicalIndex(DOCS)


def ids(index: LexicalIndex, query: str, **kwargs: object) -> list[int]:
    return [h.work_id for h in index.search(query, **kwargs)]  # type: ignore[arg-type]


def test_title_match_outranks_body_mention(index: LexicalIndex) -> None:
    assert ids(index, "murder express")[0] == 1


def test_stemming_matches_word_forms(index: LexicalIndex) -> None:
    assert 1 in ids(index, "murders")


def test_author_field_is_searchable(index: LexicalIndex) -> None:
    assert ids(index, "christie") == [1]


def test_accents_are_folded(index: LexicalIndex) -> None:
    assert ids(index, "garcia marquez") == [3]


def test_filler_words_are_ignored_but_titles_stay_findable(index: LexicalIndex) -> None:
    assert ids(index, "a good book please") == []
    assert ids(index, "the book thief")[0] == 4


def test_stopword_only_query_matches_nothing(index: LexicalIndex) -> None:
    assert ids(index, "the of and") == []


def test_mask_excludes_works(index: LexicalIndex) -> None:
    allowed = index.work_ids != 1

    assert ids(index, "murder", allowed=allowed) == [2]


def test_scores_align_with_work_ids(index: LexicalIndex) -> None:
    scores = index.scores("sorting graphs")

    assert scores.shape == (len(DOCS),)
    assert int(index.work_ids[int(np.argmax(scores))]) == 5


def test_field_weights_change_the_ranking() -> None:
    title_heavy = LexicalIndex(DOCS, {"title": 5.0, "author": 1.0, "body": 0.1})
    body_heavy = LexicalIndex(DOCS, {"title": 0.1, "author": 1.0, "body": 5.0})

    assert ids(title_heavy, "train murder")[0] == 2  # "Train" in title
    assert ids(body_heavy, "train murder")[0] in {1, 2}
    assert title_heavy.scores("train")[1] > body_heavy.scores("train")[1]
