"""The two decision rules, tested without any I/O."""

import pytest

from toolkit.deals import best_purchase, judge_deal


@pytest.mark.parametrize(
    "price, savings, low, good, reason",
    [
        (0.0, 100, 0.0, True, "free"),
        (3.99, 80, 3.99, True, "at its all-time low"),
        (5.00, 20, 4.00, True, "close to its all-time low"),  # exactly 1.25x the low
        (5.01, 20, 4.00, False, "only 20% off"),  # just above it, small discount
        (12.49, 50, 9.99, True, "50% off"),  # above 1.25x the low, but heavily discounted
        (14.99, 29, 2.99, False, "wait for a better sale"),  # discount just under the bar
        (14.99, 0, 2.99, False, "full price; has been as low as $2.99"),
        # A new release at full price is "at its all-time low" but has never been on sale.
        (69.99, 0, 69.99, False, "never been discounted"),
        (4.00, 0, 4.00, False, "never been discounted"),
    ],
)
def test_judge_deal(price, savings, low, good, reason):
    is_good, why = judge_deal(price, savings, low)
    assert is_good is good
    assert reason in why


# (name, price, saved)
CELESTE, HADES, STARDEW = ("Celeste", 4.99, 15.00), ("Hades", 12.49, 12.50), ("Stardew", 14.99, 0.0)


def plan(items, budget, must=()):
    return [
        i[0]
        for i in best_purchase(
            items, budget, price=lambda i: i[1], saved=lambda i: i[2], must_have=lambda i: i[0] in must
        )
    ]


def test_must_have_beats_bigger_savings():
    # Hades alone saves less than Celeste alone, but the user insists on Hades.
    assert plan([CELESTE, HADES], 13, must=("Hades",)) == ["Hades"]


def test_must_have_still_respects_budget():
    assert plan([CELESTE, HADES], 10, must=("Hades",)) == ["Celeste"]


def test_picks_biggest_saving_that_fits():
    assert plan([CELESTE, HADES, STARDEW], 17) == ["Celeste"]  # both would be 17.48


def test_combines_when_budget_allows():
    assert plan([CELESTE, HADES, STARDEW], 20) == ["Celeste", "Hades"]


def test_tie_on_savings_prefers_more_games():
    assert plan([CELESTE, HADES, STARDEW], 40) == ["Celeste", "Hades", "Stardew"]


def test_saving_beats_cheapness():
    cheap_small = ("Cheap", 1.00, 1.00)
    pricey_big = ("Pricey", 9.00, 30.00)
    assert plan([cheap_small, pricey_big], 9) == ["Pricey"]


def test_nothing_fits():
    assert plan([HADES], 5) == []


def test_exact_budget_is_allowed():
    assert plan([HADES], 12.49) == ["Hades"]
