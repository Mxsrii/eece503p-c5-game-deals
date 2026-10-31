"""Shared fixtures: a fake CheapShark + ntfy behind httpx.MockTransport, and an in-memory
MCP client talking to the real server object. No network is used."""

import json

import httpx
import pytest
from fastmcp import Client

import server
from toolkit.config import Settings

CHEAPSHARK = "https://cheapshark.test/api/1.0"
NTFY = "https://ntfy.test"


def game(game_id, title, offers, all_time_low, low_date=1712840581):
    """A fake game: offers = [(store_id, price, retail_price), ...]."""
    return {
        "info": {"title": title},
        "cheapestPriceEver": {"price": f"{all_time_low:.2f}", "date": low_date},
        "deals": [
            {
                "storeID": store,
                "dealID": f"deal-{game_id}-{store}",
                "price": f"{price:.2f}",
                "retailPrice": f"{retail:.2f}",
                "savings": f"{(1 - price / retail) * 100 if retail else 0:.6f}",
            }
            for store, price, retail in offers
        ],
    }


# Each game exercises a different decision.
GAMES = {
    "1": game("1", "Celeste", [("1", 7.99, 19.99), ("7", 4.99, 19.99)], all_time_low=3.99),  # near low
    "2": game("2", "Hades", [("1", 12.49, 24.99)], all_time_low=9.99),  # 50% off
    "3": game("3", "Hollow Knight", [("1", 14.99, 14.99)], all_time_low=2.99),  # wait
    "4": game("4", "Stardew Valley", [("1", 14.99, 14.99)], all_time_low=14.99),  # at low, $0 saved
    "5": game("5", "Hollow Knight: Silksong", [("1", 19.99, 19.99)], all_time_low=19.99),
}


def hit(game_id):
    return {"gameID": game_id, "external": GAMES[game_id]["info"]["title"], "cheapest": "0"}


SEARCH = {
    "celeste": [hit("1")],
    "hades": [hit("2")],
    # Like the real API: the fuzzy search ranks Silksong first.
    "hollow knight": [hit("5"), hit("3")],
    "hollow": [hit("5"), hit("3")],
    "stardew valley": [hit("4")],
}

STORES = [{"storeID": "1", "storeName": "Steam"}, {"storeID": "7", "storeName": "GOG"}]


class FakeWorld:
    """Stands in for cheapshark.test and ntfy.test; records every request."""

    def __init__(self):
        self.games = dict(GAMES)
        self.search = dict(SEARCH)
        self.cheapshark_requests: list[httpx.Request] = []
        self.ntfy_requests: list[httpx.Request] = []
        self.cheapshark_status = 200
        self.ntfy_status = 200
        self.cheapshark_down = False
        self.ntfy_down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "cheapshark.test":
            return self._cheapshark(request)
        if request.url.host == "ntfy.test":
            return self._ntfy(request)
        raise AssertionError(f"unexpected host {request.url.host}")

    def _cheapshark(self, request):
        self.cheapshark_requests.append(request)
        if self.cheapshark_down:
            raise httpx.ConnectError("down", request=request)
        if self.cheapshark_status != 200:
            return httpx.Response(self.cheapshark_status)
        path, params = request.url.path, request.url.params
        if path.endswith("/stores"):
            return httpx.Response(200, json=STORES)
        if "id" in params:
            found = self.games.get(params["id"])
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        return httpx.Response(200, json=self.search.get(params["title"].lower(), []))

    def _ntfy(self, request):
        self.ntfy_requests.append(request)
        if self.ntfy_down:
            raise httpx.ConnectError("down", request=request)
        if self.ntfy_status != 200:
            return httpx.Response(self.ntfy_status, json={"error": "nope"})
        return httpx.Response(200, json={"id": "abc", "time": 1})

    def ntfy_bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.ntfy_requests]


@pytest.fixture
def world():
    return FakeWorld()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        ntfy_topic="test-topic",
        ntfy_server=NTFY,
        cheapshark_url=CHEAPSHARK,
        db_path=tmp_path / "sent.db",
    )


def install(world, settings):
    server.set_services(
        server.build_services(settings, transport=httpx.MockTransport(world.handler), min_interval_s=0)
    )


@pytest.fixture
async def client(world, settings):
    install(world, settings)
    async with Client(server.mcp) as c:
        yield c
    server.set_services(None)
