"""Does the agent route requests to the right tool? Prompt instructions can't be
enforced in code, so this measures them instead.

    python scripts/eval_routing.py            # every case once
    python scripts/eval_routing.py --repeat 3 # catch flaky behaviour

Uses the real model and real prices (a few cents of OpenAI credit), but the server is
started WITHOUT a phone topic, so nothing can be sent: send attempts fail safely and
still count as "the agent chose send_to_phone".
"""

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import Runner, ToolCallItem  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from agent import make_agent, make_server  # noqa: E402

# (prompt, check(calls) -> problem or None). calls = [(tool_name, arguments_json), ...]
DATA, ACTION, PLAN = "get_game_price", "send_to_phone", "plan_purchases"


def first_is(tool, *, forbid=()):
    def check(calls):
        names = [n for n, _ in calls]
        if not names:
            return f"no tool called (expected {tool})"
        if names[0] != tool:
            return f"first call was {names[0]} (expected {tool})"
        bad = [n for n in names if n in forbid]
        return f"also called {bad}" if bad else None

    return check


def plan_with(**expected_args):
    def check(calls):
        problem = first_is(PLAN, forbid=(ACTION,))(calls)
        if problem:
            return problem
        args = calls[0][1]
        for key, value in expected_args.items():
            if f'"{key}":{value}' not in args.replace(" ", ""):
                return f"expected {key}={value} in {args}"
        return None

    return check


def sends_once(calls):
    """A read-only lookup first is fine; what matters is exactly one send and no planning."""
    names = [n for n, _ in calls]
    if names.count(ACTION) != 1:
        return f"{ACTION} called {names.count(ACTION)} times (expected exactly 1)"
    return f"also called {PLAN}" if PLAN in names else None


def no_tools(calls):
    return f"called {[n for n, _ in calls]} (expected none)" if calls else None


CASES = [
    ("How much is Portal 2?", first_is(DATA, forbid=(ACTION, PLAN))),
    ("Is Hogwarts Legacy a good deal right now?", first_is(DATA, forbid=(ACTION, PLAN))),
    ("How much is Zelda 99?", first_is(DATA, forbid=(ACTION, PLAN))),  # must not answer from memory
    # An earlier "remind me next week" prompt was ambiguous (the tool can't schedule), and the
    # model sometimes asked instead of sending. This phrasing asks for what the tool does.
    ("Send a note to my phone: check Hades prices on Friday.", sends_once),
    ("I have $30: Cyberpunk 2077, Terraria and Portal 2. What should I buy?", first_is(PLAN, forbid=(ACTION,))),
    ("With $20, Celeste or Terraria? Don't send anything yet.", plan_with(send="false")),
    ("I have $25 for Celeste and Terraria, but I really want Hades no matter what.", plan_with(must_have='["Hades"]')),
    ("Plan purchases for Celeste with a budget of 0 dollars.", first_is(PLAN, forbid=(ACTION,))),  # tool validates
    ("What can you help me with?", no_tools),
]


async def run_case(agent, prompt):
    result = await Runner.run(agent, prompt)
    return [
        (getattr(i.raw_item, "name", "?"), getattr(i.raw_item, "arguments", ""))
        for i in result.new_items
        if isinstance(i, ToolCallItem)
    ]


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    repeat = parser.parse_args().repeat
    load_dotenv(ROOT / ".env")

    with tempfile.TemporaryDirectory() as tmp:
        env = {"NTFY_TOPIC": "", "DB_PATH": str(Path(tmp) / "eval.db")}
        async with make_server(env) as server:
            agent = make_agent(server)
            passed = total = 0
            for prompt, check in CASES:
                for _ in range(repeat):
                    calls = await run_case(agent, prompt)
                    problem = check(calls)
                    total += 1
                    passed += problem is None
                    mark = "PASS" if problem is None else "FAIL"
                    tools = ", ".join(n for n, _ in calls) or "-"
                    print(f"{mark}  {prompt[:62]:<62}  [{tools}]" + (f"  <- {problem}" if problem else ""))
    print(f"\n{passed}/{total} passed")


if __name__ == "__main__":
    asyncio.run(main())
