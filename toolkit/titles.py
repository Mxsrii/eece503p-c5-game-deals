"""Title heuristics: is a search result another edition of the same game, an add-on, or
something else? CheapShark doesn't say, so this goes by the words in the title. It is
deliberately strict: missing a real edition is better than calling a different game
(e.g. "ELDEN RING NIGHTREIGN Deluxe Edition") an edition of "ELDEN RING".
"""

import re

# Words that name an edition by themselves...
EDITION_MARKERS = {
    "edition", "deluxe", "ultimate", "complete", "goty", "definitive", "gold", "premium",
    "enhanced", "anniversary", "cut",
}
# ...and words that may appear alongside them ("Game of the Year Edition", "Director's Cut").
EDITION_WORDS = EDITION_MARKERS | {
    "digital", "game", "of", "the", "year", "directors", "director", "special",
    "collectors", "standard", "super",
}
ADDON_WORDS = {
    "dlc", "pack", "soundtrack", "ost", "artbook", "season", "pass", "upgrade",
    "costume", "costumes", "skin", "skins", "map", "expansion", "addon",
}


def _words(title: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", title.lower().replace("'", "")).split()


def is_addon(title: str) -> bool:
    return any(w in ADDON_WORDS for w in _words(title))


def classify(base_title: str, other_title: str) -> str:
    """'edition' | 'add-on' | 'other', relative to the game that was matched."""
    if is_addon(other_title):
        return "add-on"
    base, other = _words(base_title), _words(other_title)
    if other[: len(base)] != base:
        return "other"
    rest = other[len(base):]
    # Same title followed only by edition words, at least one of which names an edition.
    if rest and all(w in EDITION_WORDS for w in rest) and any(w in EDITION_MARKERS for w in rest):
        return "edition"
    return "other"


def edition_note(base_price: float, editions: list[tuple[str, float]]) -> str | None:
    """Point out fuller editions that cost about the same as the standard one."""
    notes = []
    for title, price in sorted(editions, key=lambda e: e[1]):
        extra = price - base_price
        if extra <= 0:
            notes.append(f"{title} costs no more (${price:.2f})")
        elif extra <= max(5.0, 0.5 * base_price):
            notes.append(f"{title} is only ${extra:.2f} more (${price:.2f})")
    return "; ".join(notes) + ". It may include extra content worth considering." if notes else None
