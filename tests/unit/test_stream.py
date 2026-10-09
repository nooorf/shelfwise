import json

from shelfwise.generation.stream import Piece, PieceParser


def test_pieces_come_out_as_soon_as_they_close() -> None:
    reply = {
        "intro": 'Three "dark" picks.',
        "items": [
            {"work_id": 7, "why": "A twisty marriage."},
            {"work_id": 2, "why": "Grim, \\ tense."},
        ],
        "follow_up": "Shorter?",
    }
    text = json.dumps(reply)
    parser = PieceParser()
    seen: list[tuple[int, Piece]] = []
    for i in range(0, len(text), 3):  # three characters at a time, as tokens arrive
        seen += [(i, p) for p in parser.feed(text[i : i + 3])]

    assert [p for _, p in seen] == [
        Piece("intro", 'Three "dark" picks.'),
        Piece("item", "A twisty marriage.", 7),
        Piece("item", "Grim, \\ tense.", 2),
        Piece("follow_up", "Shorter?"),
    ]
    first_item_closes = text.index("marriage.") + len('marriage."}')
    assert seen[1][0] < first_item_closes  # emitted on the chunk that closed it, not later


def test_an_unfinished_string_waits() -> None:
    parser = PieceParser()
    assert parser.feed('{"intro": "Half a sent') == []
    assert parser.feed('ence."') == [Piece("intro", "Half a sentence.")]
