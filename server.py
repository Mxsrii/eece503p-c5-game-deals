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
from toolkit.models import GamePrice, PlannedGame, PurchasePlan, SentNotification
from toolkit.notify import NotifyError, NtfyClient
from toolkit.store import NotificationLog

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

    Searches are fuzzy: an exact title match is preferred, and exact_match is
    false (with other_matches listed) when the closest title differs from the one
    asked for, so check it before relying on the result.

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
        match = next((r for r in results if _normalise(r["external"]) == wanted), results[0])
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
    return GamePrice(
        game_id=match["gameID"],
        title=details.get("info", {}).get("title") or match["external"],
        searched_for=title,
        exact_match=_normalise(match["external"]) == wanted,
        other_matches=[r["external"] for r in results if r is not match][:3],
        store=stores.get(best["storeID"], f"store {best['storeID']}"),
        price=price,
        normal_price=normal,
        savings_percent=round(float(best["savings"]), 1),
        savings_usd=round(max(normal - price, 0), 2),
        all_time_low=float(low.get("price", price)),
        all_time_low_date=low_date,
        deal_url=f"https://www.cheapshark.com/redirect?dealID={best['dealID']}",
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
    if plan.not_found:
        lines.append("Not found: " + ", ".join(plan.not_found))
    return "\n".join(lines)


@mcp.tool
async def plan_purchases(
    wishlist: list[str],
    budget: float,
    send: bool = True,
) -> PurchasePlan:
    """Decide which wishlist games are worth buying now within a budget, and send the list to the phone.

    Use this when the user gives several games and/or a budget and asks what to buy.
    It coordinates the other two tools:
      1. get_game_price for every title (titles it cannot find are skipped and reported),
      2. judges each price: a good deal if within 25% of the game's all-time low or
         at least 30% off; otherwise "wait for a sale",
      3. picks the good deals that save the most money without going over budget,
      4. send_to_phone with the shopping list (skipped when send=false or nothing is
         worth buying).
    Nothing is sent if any price lookup fails. Prices are in USD.

    Args:
        wishlist: 1 to 10 game titles, e.g. ["Celeste", "Hades", "Hollow Knight"].
        budget: Maximum total to spend in USD, more than 0 and up to 1000.
        send: True to send the shopping list now; false to preview the plan only.
    """
    seen: set[str] = set()
    titles = []
    for t in (t.strip() for t in wishlist):
        if t and _normalise(t) not in seen:
            seen.add(_normalise(t))
            titles.append(t)
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

    good, wait = [], []
    for game in found:
        is_good, reason = judge_deal(game.price, game.savings_percent, game.all_time_low)
        (good if is_good else wait).append(PlannedGame(game=game, reason=reason))

    buy = best_purchase(good, budget, price=lambda p: p.game.price, saved=lambda p: p.game.savings_usd)
    total_cost = round(sum(p.game.price for p in buy), 2)
    plan = PurchasePlan(
        budget=budget,
        buy=buy,
        total_cost=total_cost,
        total_saved=round(sum(p.game.savings_usd for p in buy), 2),
        budget_left=round(budget - total_cost, 2),
        wait=wait,
        over_budget=[p for p in good if p not in buy],
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
