"""Manual smoke test against the REAL CheapShark API, in preview mode (nothing is sent).

    python scripts/smoke.py "Disco Elysium" "Hollow Knight" "LIMBO" --budget 15
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import plan_purchases  # noqa: E402


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("titles", nargs="+")
    parser.add_argument("--budget", type=float, default=20)
    args = parser.parse_args()

    plan = await plan_purchases(args.titles, args.budget, send=False)
    groups = (("BUY", plan.buy), ("WAIT", plan.wait), ("OVER BUDGET", plan.over_budget), ("CHECK", plan.check))
    for label, items in groups:
        for p in items:
            g = p.game
            match = "" if g.exact_match else f"  [inexact match for '{g.searched_for}']"
            print(f"{label:<12} {g.title:<38} ${g.price:>6.2f} at {g.store:<16} "
                  f"(normal ${g.normal_price:.2f}, low ${g.all_time_low:.2f}) - {p.reason}{match}")
    if plan.not_found:
        print(f"{'NOT FOUND':<12} {', '.join(plan.not_found)}")
    print(f"\nTotal ${plan.total_cost:.2f} of ${plan.budget:.2f}, saving ${plan.total_saved:.2f}")


asyncio.run(main())
