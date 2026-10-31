"""The two decision rules, tested without any I/O."""

import pytest

from toolkit.deals import best_purchase, judge_deal


@pytest.mark.parametrize(
    "price, savings, low, good, reason",
    [
        (0.0, 100, 0.0, True, "free"),
        (3.99, 80, 3.99, True, "at its all-time low"),
        (5.00, 0, 4.00, True, "close to its all-time low"),  # exactly 1.25x the low
        (5.01, 0, 4.00, False, "wait for a sale"),  # just above it, no discount
        (12.49, 50, 9.99, True, "50% off"),  # above 1.25x the low, but heavily discounted
        (14.99, 0, 2.99, False, "wait for a sale"),
        (14.99, 29, 2.99, False, "wait for a sale"),  # discount just under the bar
    ],
)
def test_judge_deal(price, savings, low, good, reason):
    is_good, why = judge_deal(price, savings, low)
    assert is_good is good
    assert reason in why


# (name, price, saved)
CELESTE, HADES, STARDEW = ("Celeste", 4.99, 15.00), ("Hades", 12.49, 12.50), ("Stardew", 14.99, 0.0)


def plan(items, budget):
    return [i[0] for i in best_purchase(items, budget, price=lambda i: i[1], saved=lambda i: i[2])]


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
