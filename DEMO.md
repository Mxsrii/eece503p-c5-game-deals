# Demo script (5–7 minutes)

Prices change daily. **An hour before recording**, run this and swap in titles that are on sale:

```bash
uv run python scripts/smoke.py "Disco Elysium" "Hollow Knight" "LIMBO" "Resident Evil 2" --budget 15
```

You want at least one BUY, one WAIT and one OVER BUDGET. Have the ntfy app open on your phone and
keep the phone in frame (or mirror it) for the notifications.

## 0:00 – Intro (≈45 s)

> "This is Game Deal Hunter, an MCP server built with FastMCP and driven by an OpenAI Agents SDK
> agent. It has three tools: `get_game_price` is the **Data** tool, it only reads prices.
> `send_to_phone` is the **Action** tool, it sends a real notification. And `plan_purchases` is the
> **Orchestration** tool, it uses the other two to decide what to buy within a budget."

Optional: show the tools in MCP Inspector (`uv run fastmcp dev inspector server.py:mcp --project .`):
list tools, open one schema, point at the description and typed arguments.

## 1:00 – Data tool alone (≈45 s)

```
uv run python agent.py
you> How much is Hollow Knight right now, and is it a good deal?
```

Point out in the trace: `-> MCP call get_game_price` and the green result. Say: the agent picked the
read-only tool, nothing was sent. Hollow Knight is full price, but its all-time low is much lower.

## 1:45 – Action tool alone (≈30 s)

```
you> Send that to my phone.
```

One `send_to_phone` call → phone buzzes. "The agent reused what it already knew; the Action tool
doesn't look anything up."

## 2:15 – Orchestration with preview (≈1 min 15 s)

```
you> I have $15. Disco Elysium, Hollow Knight, LIMBO and Resident Evil 2. What should I buy? Let me review before sending.
```

Point out `plan_purchases(... "send": false)`: buy list, wait list (Hollow Knight, with the all-time
low), over-budget games. Explain the rule: good deal = within 25% of all-time low or 30%+ off, then it
picks the combination that saves the most money within budget.

```
you> Looks good, send it.
```

Phone buzzes with "Buy N games for $X (save $Y)" and buy buttons. Tap one to show it opens the store.

## 3:30 – Failure cases (≈1 min)

```
you> How much is Zelda 99?
```
Red error: no matching game. Clear message, no guess.

```
you> Plan purchases for Celeste with a budget of 0 dollars.
```
Red error: budget must be more than 0. Nothing sent. Point at the server's own
`Error calling tool 'plan_purchases'` log line: the validation happens in the server, not the model
(the agent is instructed to let the tools validate rather than pre-judge inputs itself).

```
you> How much is Shadow Tactics?
```
Inexact match: it finds an expansion ("Aiko's Choice"), and the agent warns that the match may be a
different game. "Predictable tools can still return the wrong data, so I made it visible."

## 4:30 – Resource + tests (≈45 s)

```
you> /sent
```
Reads `notifications://sent`, a resource, not a tool: it does no work, it just exposes state.

Then in a second terminal: `uv run pytest -q` → 57 passed. "All HTTP is faked, so the tests cover
every failure case without the network."

## 5:15 – Challenges (≈1 min)

- Keeping tools single-purpose: `send_to_phone` is generic on purpose; the deal logic stays in the
  orchestrator.
- The orchestrator holds the maths the model is unreliable at (the budget optimisation).
- Irreversible actions: preview mode before sending.
- Fuzzy search: exact matches win, otherwise the agent warns.

## 6:15 – Wrap-up (≈20 s)

Show the GitHub repo URL. Done.
