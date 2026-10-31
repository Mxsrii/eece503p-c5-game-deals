"""Game Deal Hunter MCP server.

Exactly three tools, one per category:
  - get_game_price   (Data)          read-only price lookup on CheapShark
  - send_to_phone    (Action)        push notification via ntfy
  - plan_purchases   (Orchestration) prices a wishlist, decides buy/wait, fits a budget, sends
plus one read-only resource, notifications://sent.

Run directly for stdio transport:  python server.py
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from toolkit.cheapshark import CheapSharkClient, CheapSharkError
from toolkit.config import USER_AGENT, Settings
from toolkit.deals import best_purchase, judge_deal
from toolkit.models import GameMatch, GamePrice, PlannedGame, PurchasePlan, SentNotification
from toolkit.notify import NotifyError, NtfyClient
from toolkit.store import NotificationLog
from toolkit.titles import classify, edition_note, is_addon

mcp = FastMCP(
    name="game-deal-hunter",
    instructions=(
        "Look up live PC game prices across stores, send messages to the user's phone, "
        "and plan which wishlist games to buy now within a budget."
    ),
)

MAX_WISHLIST = 10
MAX_BUDGET = 1000.0


@dataclass
class Services:
    settings: Settings
    cheapshark: CheapSharkClient
    ntfy: NtfyClient
    log: NotificationLog


_services: Services | None = None


def build_services(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    min_interval_s: float = 0.3,
) -> Services:
    http = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=10.0, transport=transport)
    return Services(
        settings=settings,
        cheapshark=CheapSharkClient(settings.cheapshark_url, http, min_interval_s),
        ntfy=NtfyClient(settings.ntfy_server, http),
        log=NotificationLog(settings.db_path),
    )


def get_services() -> Services:
    global _services
    if _services is None:
        _services = build_services(Settings.from_env())
    return _services


def set_services(services: Services | None) -> None:
    """Swap the service layer (used by tests to inject fake HTTP)."""
    global _services
    _services = services


class GameNotFound(ToolError):
    """No game matched. Separate from service errors so the planner can skip just this title."""


def _normalise(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


# ---------------------------------------------------------------- Data tool


@mcp.tool
async def get_game_price(title: str) -> GamePrice:
    """Look up the current best price of one PC game across stores. Read-only.

    Compares stores such as Steam, GOG, Humble and Fanatical via CheapShark, and
    also returns the lowest price the game has ever had, which tells you whether
    today's price is actually a good deal. Prices are in USD.

    Searches are fuzzy: an exact title match is preferred. When the closest title
    differs from the one asked for (e.g. a franchise name like "spongebob"),
    exact_match is false, `warning` explains it, and other_matches lists every other
    game found with its current lowest price: show them and ask which one is meant.

    Each of other_matches has a kind: "edition" (Deluxe, Ultimate... of the same game),
    "add-on" (DLC, soundtrack, upgrade: needs the game, never a cheaper copy of it) or
    "other". The price is for the exact edition matched; edition_note points out a
    fuller edition that costs about the same.

    Args:
        title: The game's name, e.g. "Hollow Knight" or "Celeste".
    """
    title = title.strip()
    if not title:
        raise ToolError("title must not be empty.")
    if len(title) > 100:
        raise ToolError(f"title is too long ({len(title)} characters, max 100).")

    services = get_services()
    try:
        results = await services.cheapshark.search_games(title)
        if not results:
            raise GameNotFound(f"No game matching '{title}' was found. Check the spelling.")
        wanted = _normalise(title)
        # Exact title first; otherwise the first result that isn't an add-on (a $2 costume
        # pack is never the game someone asked about).
        match = next(
            (r for r in results if _normalise(r["external"]) == wanted),
            next((r for r in results if not is_addon(r["external"])), results[0]),
        )
        details = await services.cheapshark.game_details(match["gameID"])
        if not details or not details.get("deals"):
            raise GameNotFound(f"'{match['external']}' has no current offers in any store.")
        stores = await services.cheapshark.store_names()
    except CheapSharkError as exc:
        raise ToolError(str(exc)) from exc

    best = min(details["deals"], key=lambda d: (float(d["price"]), -float(d["savings"])))
    price, normal = float(best["price"]), float(best["retailPrice"])
    low = details.get("cheapestPriceEver") or {}
    low_date = (
        datetime.fromtimestamp(low["date"], timezone.utc).date().isoformat() if low.get("date") else None
    )
    matched_title = details.get("info", {}).get("title") or match["external"]
    # The search results already carry each game's cheapest price, so listing every
    # alternative costs no extra requests.
    others = [
        GameMatch(
            game_id=r["gameID"],
            title=r["external"],
            cheapest_price=float(r.get("cheapest") or 0),
            kind=classify(match["external"], r["external"]),
        )
        for r in results
        if r is not match
    ]
    exact = _normalise(match["external"]) == wanted
    warning = None
    if not exact:
        warning = f"'{title}' matched '{matched_title}', which may be a different game"
        candidates = [o for o in others if o.kind != "add-on"]
        if candidates:
            names = ", ".join(o.title for o in candidates[:3])
            more = f" and {len(candidates) - 3} more" if len(candidates) > 3 else ""
            warning += f". Also found: {names}{more}. Ask which one they mean."
        else:
            warning += "."
    return GamePrice(
        game_id=match["gameID"],
        title=matched_title,
        searched_for=title,
        exact_match=exact,
        other_matches=others,
        store=stores.get(best["storeID"], f"store {best['storeID']}"),
        price=price,
        normal_price=normal,
        savings_percent=round(float(best["savings"]), 1),
        savings_usd=round(max(normal - price, 0), 2),
        all_time_low=float(low.get("price", price)),
        all_time_low_date=low_date,
        deal_url=f"https://www.cheapshark.com/redirect?dealID={best['dealID']}",
        warning=warning,
        edition_note=edition_note(
            price, [(o.title, o.cheapest_price) for o in others if o.kind == "edition"]
        ),
    )


# -------------------------------------------------------------- Action tool


@mcp.tool
async def send_to_phone(
    title: str,
    message: str,
    links: dict[str, str] | None = None,
) -> SentNotification:
    """Send one push notification to the user's phone.

    This has a real external effect: every call delivers a new notification and
    cannot be undone. Only call it when the user asks to send, share or notify.
    It does not look anything up.

    Args:
        title: Notification title (max 100 characters).
        message: Notification body (max 2000 characters).
        links: Optional buttons as {"label": "https://..."}, at most 3. Tapping the
            notification opens the first one.

    Returns the logged record of what was sent. Nothing is logged if sending fails.
    """
    title, message, links = title.strip(), message.strip(), links or {}
    if not title or len(title) > 100:
        raise ToolError("title must be 1 to 100 characters.")
    if not message or len(message) > 2000:
        raise ToolError("message must be 1 to 2000 characters.")
    if len(links) > 3:
        raise ToolError(f"At most 3 links are allowed (got {len(links)}).")
    for label, url in links.items():
        if not label.strip() or len(label) > 40:
            raise ToolError("Each link label must be 1 to 40 characters.")
        if not url.startswith(("https://", "http://")):
            raise ToolError(f"Link '{label}' must be an http(s) URL.")

    services = get_services()
    topic = services.settings.ntfy_topic
    if not topic:
        raise ToolError("No phone is configured: set NTFY_TOPIC in .env. Nothing was sent.")
    try:
        await services.ntfy.publish(topic=topic, title=title, message=message, links=links)
    except NotifyError as exc:
        raise ToolError(str(exc)) from exc
    return services.log.add(title=title, message=message, links=links, topic=topic)


# ------------------------------------------------------- Orchestration tool


def _shopping_message(plan: PurchasePlan) -> str:
    lines = [
        f"Buy {g.game.title}: ${g.game.price:.2f} at {g.game.store} ({g.reason})" for g in plan.buy
    ]
    lines += [f"Wait on {g.game.title}: ${g.game.price:.2f} now, {g.reason}" for g in plan.wait]
    lines += [f"Over budget: {g.game.title} (${g.game.price:.2f})" for g in plan.over_budget]
    lines += [f"Check: {g.reason}" for g in plan.check]
    if plan.not_found:
        lines.append("Not found: " + ", ".join(plan.not_found))
    return "\n".join(lines)


@mcp.tool
async def plan_purchases(
    wishlist: list[str],
    budget: float,
    must_have: list[str] | None = None,
    send: bool = True,
) -> PurchasePlan:
    """Decide which wishlist games are worth buying now within a budget, and send the list to the phone.

    Use this when the user gives several games and/or a budget and asks what to buy.
    It coordinates the other two tools:
      1. get_game_price for every title. Titles it cannot find are skipped and
         reported; inexact matches go to `check` and are never bought automatically.
      2. Judges each price. A game must be discounted right now, and then counts as
         a good deal if within 25% of its all-time low or at least 30% off.
         Otherwise "wait" (full-price games, including new releases, always wait).
      3. Picks what to buy within budget: must-haves first (even if the price is not
         great), then the good deals that save the most money.
      4. send_to_phone with the shopping list (skipped when send=false or nothing is
         worth buying).
    Nothing is sent if any price lookup fails. Prices are in USD.

    Args:
        wishlist: 1 to 10 game titles, e.g. ["Celeste", "Hades", "Hollow Knight"].
        budget: Maximum total to spend in USD, more than 0 and up to 1000.
        must_have: Titles the user really wants regardless of price, e.g. ["Hades"].
            They are added to the wishlist if missing.
        send: True to send the shopping list now; false to preview the plan only.
    """
    seen: set[str] = set()
    titles = []
    for t in (t.strip() for t in [*wishlist, *(must_have or [])]):
        if t and _normalise(t) not in seen:
            seen.add(_normalise(t))
            titles.append(t)
    wanted = {_normalise(t) for t in (must_have or []) if t.strip()}
    if not 1 <= len(titles) <= MAX_WISHLIST:
        raise ToolError(f"wishlist must contain 1 to {MAX_WISHLIST} game titles (got {len(titles)}).")
    if not 0 < budget <= MAX_BUDGET:
        raise ToolError(f"budget must be more than 0 and at most {MAX_BUDGET:g} USD (got {budget}).")

    found: list[GamePrice] = []
    not_found: list[str] = []
    for title in titles:
        try:
            game = await get_game_price(title)
        except GameNotFound:
            not_found.append(title)
            continue
        if all(g.game_id != game.game_id for g in found):
            found.append(game)
    if not found:
        raise ToolError(f"None of the games were found: {', '.join(not_found)}. Nothing was sent.")

    candidates, wait, check = [], [], []
    priority: set[str] = set()
    for game in found:
        if not game.exact_match:
            check.append(PlannedGame(game=game, reason=game.warning or "inexact match"))
            continue
        is_good, reason = judge_deal(game.price, game.savings_percent, game.all_time_low)
        if _normalise(game.searched_for) in wanted:
            priority.add(game.game_id)
            if not is_good:
                reason = f"not a deal right now (has been as low as ${game.all_time_low:.2f})"
            candidates.append(PlannedGame(game=game, reason=f"must-have; {reason}"))
        elif is_good:
            candidates.append(PlannedGame(game=game, reason=reason))
        else:
            wait.append(PlannedGame(game=game, reason=reason))

    buy = best_purchase(
        candidates,
        budget,
        price=lambda p: p.game.price,
        saved=lambda p: p.game.savings_usd,
        must_have=lambda p: p.game.game_id in priority,
    )
    total_cost = round(sum(p.game.price for p in buy), 2)
    plan = PurchasePlan(
        budget=budget,
        buy=buy,
        total_cost=total_cost,
        total_saved=round(sum(p.game.savings_usd for p in buy), 2),
        budget_left=round(budget - total_cost, 2),
        wait=wait,
        over_budget=[p for p in candidates if p not in buy],
        check=check,
        not_found=not_found,
        notification=None,
    )

    if send and buy:
        n = len(buy)
        title = f"Buy {n} game{'s' if n > 1 else ''} for ${plan.total_cost:.2f} (save ${plan.total_saved:.2f})"
        links = {f"Buy {p.game.title}"[:40]: p.game.deal_url for p in buy[:3]}
        try:
            plan.notification = await send_to_phone(title, _shopping_message(plan), links)
        except ToolError as exc:
            raise ToolError(
                f"Planned to buy {', '.join(p.game.title for p in buy)} but could not send the list: {exc}"
            ) from exc
    return plan


# ----------------------------------------------------------------- Resource


@mcp.resource("notifications://sent", mime_type="application/json")
def sent_notifications() -> list[dict]:
    """The 50 most recent notifications sent to the phone, newest first. Read-only."""
    return [n.model_dump() for n in get_services().log.recent(50)]


if __name__ == "__main__":
    mcp.run(show_banner=False)
