# Spec: Game Deal Hunter MCP Toolkit

EECE 503P/798S — C5 Agent Tools. A FastMCP server with exactly three tools (Data, Action,
Orchestration) and one read-only resource, driven by an OpenAI Agents SDK agent.

## Objective

Help a gamer decide **what to buy now and what to wait for**, within a budget. The user gives a
wishlist and a budget; the toolkit looks up live prices across stores, judges each price against
the game's all-time low, picks the set of good deals that saves the most money within budget, and
sends the shopping list to the user's phone.

## Tools

### Data — `get_game_price(title)`
Read-only. Looks the game up on CheapShark (price comparison across Steam, GOG, Humble, …).
Returns `GamePrice`: matched title, whether it matched exactly, other close matches, cheapest
store, current price, normal price, % and $ saved, all-time low (and its date), buy link. USD.

Errors: empty/too-long title; no matching game; CheapShark unreachable, rate-limiting or failing.

### Action — `send_to_phone(title, message, links=None)`
External effect: one push notification via ntfy (up to 3 link buttons; tapping opens the first).
Logs it. Not idempotent: every call notifies again.

Errors: empty/too-long title or message; more than 3 links; non-http(s) link; `NTFY_TOPIC` unset;
ntfy unreachable or rejecting. Nothing is logged unless the push succeeded.

### Orchestration — `plan_purchases(wishlist, budget, send=True)`
1. `get_game_price` for each title (1–10 titles, duplicates removed). Unknown titles are skipped
   and reported; if none are found it is an error.
2. Judge each: **good deal now** if price ≤ 1.25 × all-time low or ≥ 30 % off; otherwise **wait**.
3. Among good deals, choose the subset within `budget` that maximises total $ saved
   (tie-break: more games, then lower spend). Exact search over all subsets (≤ 2¹⁰).
4. If anything is worth buying and `send` is true, `send_to_phone` with the list (one notification).

Returns buy list, totals, wait list, good-but-over-budget list, not-found titles, notification
(null in preview mode or when nothing is worth buying). Nothing is sent if any lookup fails.

## Resource
`notifications://sent` — the 50 most recent notifications, newest first.

## Configuration (`.env`, never committed)
`OPENAI_API_KEY`, `OPENAI_MODEL` (optional), `NTFY_TOPIC`, `NTFY_SERVER` (default ntfy.sh),
`CHEAPSHARK_URL` (default `https://www.cheapshark.com/api/1.0`), `DB_PATH` (default `data/sent.db`).

## Decisions
- Search is fuzzy ("Hollow Knight" also returns "Silksong"), so exact title matches win and every
  answer reports what was matched.
- USD only; a currency conversion would need a second Data tool.
- CheapShark is free and keyless; the client throttles, caches and identifies itself.

## Testing
All HTTP faked with `httpx.MockTransport`; pure deal logic unit-tested; tools tested through an
in-memory `fastmcp.Client`. No network or OpenAI calls in tests.
