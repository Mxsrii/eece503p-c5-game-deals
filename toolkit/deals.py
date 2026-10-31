"""Pure decision logic for the purchase planner. No I/O, so it is easy to test."""

from itertools import combinations
from typing import Callable, Sequence, TypeVar

# A price counts as a good deal when it is close to the lowest price the game has ever
# had, or simply heavily discounted right now.
MAX_ABOVE_ALL_TIME_LOW = 1.25
MIN_SAVINGS_PERCENT = 30.0

T = TypeVar("T")


def judge_deal(price: float, savings_percent: float, all_time_low: float) -> tuple[bool, str]:
    """Decide "buy now" vs "wait" and explain why in one short phrase."""
    if price == 0:
        return True, "free right now"
    if price <= all_time_low * MAX_ABOVE_ALL_TIME_LOW:
        if price <= all_time_low:
            return True, f"at its all-time low (${all_time_low:.2f})"
        return True, f"close to its all-time low of ${all_time_low:.2f}"
    if savings_percent >= MIN_SAVINGS_PERCENT:
        return True, f"{savings_percent:.0f}% off"
    return False, f"has been as low as ${all_time_low:.2f}; wait for a sale"


def best_purchase(
    items: Sequence[T],
    budget: float,
    price: Callable[[T], float],
    saved: Callable[[T], float],
) -> list[T]:
    """The subset within budget that saves the most money.

    Ties go to more games, then to spending less. Checks every subset, which is exact
    and instant for the 10 items the planner allows (at most 1,024 subsets).
    """
    best: tuple = ((0.0, 0, 0.0), ())
    for size in range(1, len(items) + 1):
        for combo in combinations(items, size):
            cost = sum(price(i) for i in combo)
            if cost > budget + 1e-9:
                continue
            score = (round(sum(saved(i) for i in combo), 2), len(combo), -round(cost, 2))
            if score > best[0]:
                best = (score, combo)
    return list(best[1])
