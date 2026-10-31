"""Typed tool outputs. Field descriptions end up in the MCP output schemas."""

from pydantic import BaseModel, Field


class GamePrice(BaseModel):
    game_id: str = Field(description="CheapShark game id")
    title: str = Field(description="The game that was matched")
    searched_for: str = Field(description="The title that was asked for")
    exact_match: bool = Field(description="False when the closest title differs from the request")
    other_matches: list[str] = Field(description="Other titles the search also found (up to 3)")
    store: str = Field(description="Store with the lowest current price")
    price: float = Field(description="Lowest current price in USD")
    normal_price: float = Field(description="That store's normal price in USD")
    savings_percent: float = Field(description="Discount off the normal price, 0-100")
    savings_usd: float = Field(description="Normal price minus current price")
    all_time_low: float = Field(description="Lowest price this game has ever had, USD")
    all_time_low_date: str | None = Field(description="When the all-time low happened (YYYY-MM-DD)")
    deal_url: str = Field(description="Link to buy at the lowest price")
    warning: str | None = Field(
        default=None,
        description="Set when the match is not exact: tell the user it may be a different game",
    )


class SentNotification(BaseModel):
    id: int = Field(description="Row id in the notification log")
    title: str
    message: str
    links: dict[str, str] = Field(description="Button label -> URL")
    topic: str = Field(description="ntfy topic it was published to")
    sent_at: str = Field(description="UTC timestamp, ISO 8601")


class PlannedGame(BaseModel):
    game: GamePrice
    reason: str = Field(description="Why it is (or is not) a good deal right now")


class PurchasePlan(BaseModel):
    budget: float
    buy: list[PlannedGame] = Field(description="Good deals chosen within budget")
    total_cost: float
    total_saved: float = Field(description="Sum of normal price minus price over the buy list")
    budget_left: float
    wait: list[PlannedGame] = Field(description="Not a good deal right now")
    over_budget: list[PlannedGame] = Field(
        description="Good deals or must-haves that did not fit the budget"
    )
    check: list[PlannedGame] = Field(
        description="Inexact title matches, never bought automatically: confirm the right game first"
    )
    not_found: list[str] = Field(description="Wishlist titles with no matching game")
    notification: SentNotification | None = Field(
        description="What was sent; null in preview mode or when nothing is worth buying"
    )
