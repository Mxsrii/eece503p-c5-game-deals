"""Edition / add-on heuristics, using real titles CheapShark returned."""

import pytest

from toolkit.titles import classify, edition_note, is_addon


@pytest.mark.parametrize(
    "base, other, kind",
    [
        ("Hogwarts Legacy", "Hogwarts Legacy: Deluxe Edition", "edition"),
        ("Hogwarts Legacy", "Hogwarts Legacy: Digital Deluxe Edition", "edition"),
        ("Hogwarts Legacy", "Hogwarts Legacy: Dark Arts Pack", "add-on"),
        ("Hogwarts Legacy", "Hogwarts Legacy and Quidditch Champions Deluxe Bundle", "other"),
        ("Cyberpunk 2077", "Cyberpunk 2077: Ultimate Edition", "edition"),
        ("Cyberpunk 2077", "Cyberpunk 2077 - Piggyback Interactive Map", "add-on"),
        ("Cyberpunk 2077", "Cyberpunk 2077: Phantom Liberty", "other"),  # expansion, no keyword
        ("ELDEN RING", "ELDEN RING Deluxe Edition", "edition"),
        ("ELDEN RING", "ELDEN RING NIGHTREIGN Deluxe Edition", "other"),  # a different game
        ("The Witcher 3: Wild Hunt", "The Witcher 3: Wild Hunt - Complete Edition", "edition"),
        ("The Witcher 3: Wild Hunt", "The Witcher 3: Wild Hunt Expansion Pass", "add-on"),
        ("Red Dead Redemption 2", "Red Dead Redemption 2: Ultimate Edition", "edition"),
        ("Baldur's Gate 3", "Baldurs Gate 3 - Digital Deluxe Edition upgrade", "add-on"),
        ("Fallout 4", "Fallout 4: Game of the Year Edition", "edition"),
        ("SpongeBob SquarePants: The Cosmic Shake", "SpongeBob SquarePants: The Cosmic Shake - Costume Pack DLC", "add-on"),
        ("Celeste", "Celeste", "other"),  # nothing after the title
    ],
)
def test_classify(base, other, kind):
    assert classify(base, other) == kind


def test_is_addon():
    assert is_addon("Disco Elysium - The Final Cut Soundtrack")
    assert not is_addon("Disco Elysium - The Final Cut")


def test_edition_note_for_close_or_cheaper_editions():
    note = edition_note(13.46, [("Red Dead Redemption 2: Ultimate Edition", 17.96)])
    assert note.startswith("Red Dead Redemption 2: Ultimate Edition is only $4.50 more ($17.96)")
    assert "costs no more ($5.00)" in edition_note(5.99, [("X Deluxe Edition", 5.00)])


def test_no_note_when_editions_cost_much_more():
    assert edition_note(5.99, [("Hogwarts Legacy: Deluxe Edition", 69.99)]) is None
    assert edition_note(5.99, []) is None
