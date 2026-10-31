# Game Deal Hunter — an MCP toolkit

EECE 503P/798S · C5 Agent Tools

An MCP server built with **FastMCP** that exposes exactly three tools, one per category, plus one
read-only resource. An agent built with the **OpenAI Agents SDK** acts as the MCP host/client and
routes requests to the right tool.

You give it a wishlist and a budget; it checks live prices across PC game stores, decides which games
are actually a good deal right now (compared with each game's all-time low), picks the combination
that saves the most money within your budget, and sends the shopping list to your phone.

| Tool | Category | What it does |
|---|---|---|
| `get_game_price(title)` | **Data** | Cheapest current price across stores (Steam, GOG, Humble, …), normal price, % off, all-time low and a buy link. Read-only. |
| `send_to_phone(title, message, links)` | **Action** | Sends one push notification to your phone via [ntfy](https://ntfy.sh), with up to 3 link buttons. Logged. |
| `plan_purchases(wishlist, budget, send)` | **Orchestration** | Calls `get_game_price` for each game, judges *buy now* vs *wait*, picks the subset within budget that saves the most, then calls `send_to_phone` once. `send=false` previews without sending. |
| `notifications://sent` | Resource | The 50 most recent notifications, newest first. |

Write-ups: [Part 1 summary](SUMMARY.md) · [Reflection](REFLECTION.md) · [Demo script](DEMO.md) · [Design spec](SPEC.md)

Demo video: _add link here_

## How it fits together

```
  you ──► agent.py  (OpenAI Agents SDK: MCP host + client)
              │   JSON-RPC over stdio
              ▼
          server.py (FastMCP server)
              ├── get_game_price ──────► CheapShark API (prices, all-time lows)
              ├── send_to_phone ───────► ntfy.sh ──► your phone
              ├── plan_purchases ──► calls the two tools above
              └── notifications://sent ◄── SQLite log
```

`agent.py` starts `server.py` as a subprocess and prints every tool call and result, so the full
round trip (agent → MCP client → MCP server → outside world → back) is visible.

## Setup (about 5 minutes)

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), an OpenAI API key, and the free
ntfy app on your phone ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) /
[iOS](https://apps.apple.com/app/ntfy/id1625396347)).

```bash
git clone https://github.com/Mxsrii/eece503p-c5-game-deals.git
cd eece503p-c5-game-deals
uv sync                      # creates .venv and installs everything
cp .env.example .env         # Windows: copy .env.example .env
```

Edit `.env`:

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | for the agent | Tests and the server don't need it |
| `NTFY_TOPIC` | for sending | Pick a hard-to-guess name, e.g. `game-deals-k3v9x2`; the topic name is the only access control |
| `OPENAI_MODEL` | no | Defaults to the Agents SDK default model |
| `NTFY_SERVER`, `CHEAPSHARK_URL`, `DB_PATH` | no | Defaults work |

In the ntfy app, tap **+** and subscribe to the same topic name. No phone? Open
`https://ntfy.sh/<your-topic>` in a browser instead.

## Run

```bash
uv run python agent.py                                   # chat with the agent
uv run python agent.py "Is Hollow Knight a good deal right now?"   # one request
uv run pytest                                            # tests (no network, no API key)
uv run python scripts/smoke.py "Celeste" "Hades" --budget 20       # real prices, sends nothing
uv run fastmcp dev inspector server.py:mcp --project .   # browse/call the tools in MCP Inspector
```

In the chat, `/sent` reads the `notifications://sent` resource and `/quit` exits.

Example requests:

- *"How much is Disco Elysium and is it worth buying now?"* → `get_game_price`
- *"Send that to my phone."* → `send_to_phone`
- *"I have $15. Disco Elysium, Hollow Knight, LIMBO or Resident Evil 2 — what should I buy?"* → `plan_purchases`
- *"Same list, but let me review before you send anything."* → `plan_purchases(send=false)`

## Design decisions

- **Single-purpose tools.** `get_game_price` only reads. `send_to_phone` only sends and knows nothing
  about games. All judgement lives in `plan_purchases`, which reaches the outside world only through
  the other two tools (it literally calls them).
- **The orchestrator holds the logic a model is bad at.** "Good deal" means within 25% of the
  all-time low or at least 30% off. Choosing what to buy is a small knapsack problem: the planner
  checks every subset of the (at most 10) good deals and keeps the one that saves the most money
  within budget, breaking ties by more games and then lower spend. Both rules live in
  `toolkit/deals.py` as pure functions.
- **Preview before an irreversible action.** Notifications can't be unsent, so the planner has a
  `send=false` mode and the agent is told to use it when the user wants to review first.
- **Visible uncertainty.** CheapShark's search is fuzzy ("Hollow Knight" also returns "Silksong").
  Exact title matches win; otherwise `exact_match` is false, the alternatives are listed, and the
  agent is instructed to warn the user.
- **Being a polite API client.** Identifying User-Agent, a throttle between requests and an
  in-process cache.

## Failure handling

Every tool validates its input and raises a clear `ToolError` instead of failing silently. The tests
cover each case.

| Tool | Failure | Behaviour |
|---|---|---|
| `get_game_price` | empty or too-long title; no match; game with no offers; service down, rate-limited or erroring | Clear error message; nothing is guessed |
| `send_to_phone` | empty or too-long text; >3 links; non-http link; no topic configured; ntfy down or rejecting | Clear error; **nothing is logged unless the push succeeded** |
| `plan_purchases` | empty or >10 games; budget ≤ 0 or > $1000; none of the games found; any price lookup failing; push failing | Clear error; **nothing is sent unless every lookup succeeded**. Titles that aren't found are skipped and reported, not fatal. If sending fails, the error still names what was planned. |

## Project layout

```
server.py             FastMCP server: 3 tools + 1 resource
agent.py              OpenAI Agents SDK host (stdio), prints the tool-call trace
toolkit/
  cheapshark.py       throttled, cached CheapShark client
  deals.py            buy-or-wait rule and budget optimiser (pure functions)
  notify.py           ntfy publisher
  store.py            SQLite notification log
  models.py           typed tool outputs (Pydantic)
  config.py           settings from .env
tests/                57 tests; HTTP faked with httpx.MockTransport
scripts/smoke.py      real-API check in preview mode
```

## Limitations

- Prices are USD only; converting currencies would need another Data tool.
- Two different games can share a title (the 1998 *Resident Evil 2* and the 2019 remake); the tool
  picks the first exact match.
- "All-time low" is CheapShark's record across the stores it tracks, not every store in the world.

Price data from [CheapShark](https://www.cheapshark.com). Notifications by [ntfy](https://ntfy.sh).
