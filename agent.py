"""MCP host: an OpenAI Agents SDK agent connected to server.py over stdio.

    python agent.py                      interactive chat
    python agent.py "your request"       one request, then exit

Every tool call and result is printed, so the round trip
agent -> MCP client -> MCP server -> back is visible.
In chat, type /sent to read the notifications://sent resource, /quit to exit.
"""

import ast
import asyncio
import json
import os
import sys
from pathlib import Path

from agents import Agent, Runner, ToolCallItem, ToolCallOutputItem
from agents.mcp import MCPServerStdio
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

INSTRUCTIONS = """\
You help people buy PC games at good prices, using three MCP tools. Pick the right one:

- get_game_price (read-only): the price of one game, where it is cheapest, and its
  all-time low. Use it for questions like "how much is X?" or "is X on sale?".
- send_to_phone (has a real effect): only when the user asks to send, share or notify.
  Each call sends a new notification, so never call it twice for the same request.
- plan_purchases: whenever the user mentions a budget, or asks which of several games
  to buy. Do not compare prices yourself with get_game_price for this: the planner
  applies the buy-or-wait rule and the budget optimisation. If they say not to send
  anything (yet), use send=false. By default it sends the shopping list to the phone itself, so do not call
  send_to_phone afterwards. If the user wants to review first, call it with send=false,
  show the plan, and send only if they confirm (call it again with send=true). If the
  user says they really want or must have a game, pass it in must_have.

Always say which game each title was matched to. Whenever a result has a `warning`
(the title was not an exact match, e.g. a franchise name like "spongebob"), list the
matched game and all other_matches with their prices, and ask which one they mean;
they can then give the exact title. If a plan has entries in `check`, say they were
not bought because the match may be a different game.
The tools are the only source of truth. Never answer a price, availability or "can't
find" question from your own knowledge: always call the tool, even if a title looks
made up. Do not pre-validate arguments yourself either (e.g. a budget of 0): pass them
to the tool and let it return its error.

Prices are in USD. Never invent prices; only use what the tools return. If a tool
returns an error, explain it plainly and suggest what the user could change.
Keep answers short.
"""

DIM, CYAN, GREEN, RED, RESET = "\033[2m", "\033[36m", "\033[32m", "\033[31m", "\033[0m"


def shorten(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " ..."


def tool_text(output) -> str:
    """Pull the text out of an MCP content item, which may arrive as a dict or its repr."""
    if isinstance(output, str):
        try:
            output = ast.literal_eval(output)
        except (ValueError, SyntaxError):
            return output
    if isinstance(output, dict) and output.get("type") == "text":
        return str(output.get("text", ""))
    if isinstance(output, list):
        return " ".join(tool_text(o) for o in output)
    return str(output)


def show_trace(items) -> None:
    for item in items:
        if isinstance(item, ToolCallItem):
            raw = item.raw_item
            print(f"{CYAN}  -> MCP call   {getattr(raw, 'name', '?')}({shorten(getattr(raw, 'arguments', ''), 200)}){RESET}")
        elif isinstance(item, ToolCallOutputItem):
            text = tool_text(item.output)
            # Successful tools return JSON objects; errors come back as plain text.
            colour = GREEN if text.startswith("{") else RED
            print(f"{colour}  <- MCP result {shorten(text)}{RESET}")


async def show_sent(server: MCPServerStdio) -> None:
    result = await server.read_resource("notifications://sent")
    rows = json.loads(result.contents[0].text)
    if not rows:
        print("  (nothing sent yet)")
    for r in rows:
        print(f"  #{r['id']} {r['sent_at']}  {r['title']}")


def make_server(env_overrides: dict[str, str] | None = None) -> MCPServerStdio:
    """The MCP client for server.py, launched as a subprocess over stdio."""
    params: dict = {"command": sys.executable, "args": [str(ROOT / "server.py")], "cwd": str(ROOT)}
    if env_overrides:
        params["env"] = {**os.environ, **env_overrides}
    return MCPServerStdio(
        name="game-deal-hunter",
        params=params,
        cache_tools_list=True,
        client_session_timeout_seconds=30,
    )


def make_agent(server: MCPServerStdio) -> Agent:
    return Agent(
        name="Game Deal Hunter",
        instructions=INSTRUCTIONS,
        mcp_servers=[server],
        **({"model": os.environ["OPENAI_MODEL"]} if os.getenv("OPENAI_MODEL") else {}),
    )


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if os.name == "nt":
        os.system("")  # turn on ANSI colours in older Windows consoles
    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Put it in .env (see README).")

    async with make_server() as server:
        agent = make_agent(server)
        tools = [t.name for t in await server.list_tools()]
        print(f"{DIM}Connected to MCP server 'game-deal-hunter' over stdio. Tools: {', '.join(tools)}{RESET}")

        one_shot = " ".join(sys.argv[1:]).strip()
        history: list = []
        while True:
            prompt = one_shot or input("\nyou> ").strip()
            if prompt in ("/quit", "/exit"):
                break
            if prompt == "/sent":
                await show_sent(server)
                continue
            if not prompt:
                continue

            result = await Runner.run(agent, history + [{"role": "user", "content": prompt}])
            show_trace(result.new_items)
            print(f"\nagent> {result.final_output}")
            history = result.to_input_list()
            if one_shot:
                break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
