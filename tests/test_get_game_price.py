import time

import httpx
import pytest
from fastmcp.exceptions import ToolError

from toolkit.cheapshark import CheapSharkClient, CheapSharkError
from toolkit.config import USER_AGENT

from .conftest import CHEAPSHARK


async def price(client, title):
    return (await client.call_tool("get_game_price", {"title": title})).structured_content


async def test_cheapest_store_and_history(client):
    out = await price(client, "Celeste")
    assert out["title"] == "Celeste" and out["exact_match"] is True
    assert out["store"] == "GOG" and out["price"] == 4.99  # cheaper than Steam's 7.99
    assert out["normal_price"] == 19.99
    assert out["savings_usd"] == 15.0 and out["savings_percent"] == pytest.approx(75.0, abs=0.1)
    assert out["all_time_low"] == 3.99 and out["all_time_low_date"] == "2024-04-11"
    assert out["deal_url"] == "https://www.cheapshark.com/redirect?dealID=deal-1-7"


async def test_exact_title_beats_search_ranking(client):
    out = await price(client, "Hollow Knight")
    assert out["title"] == "Hollow Knight"  # not Silksong, which the search ranked first
    assert out["exact_match"] is True and out["warning"] is None
    assert out["other_matches"] == ["Hollow Knight: Silksong"]


async def test_inexact_match_carries_a_warning(client):
    out = await price(client, "hollow")
    assert out["exact_match"] is False
    assert out["title"] == "Hollow Knight: Silksong"
    assert out["searched_for"] == "hollow"
    assert out["warning"] == (
        "'hollow' matched 'Hollow Knight: Silksong', which may be a different game "
        "(also found: Hollow Knight)."
    )


async def test_requests_identify_the_app_and_are_cached(client, world):
    await price(client, "Celeste")
    await price(client, "Celeste")
    assert world.cheapshark_requests[0].headers["User-Agent"] == USER_AGENT
    assert len(world.cheapshark_requests) == 3  # search, details, stores, then all cached


# ------------------------------------------------------------ failure cases


@pytest.mark.parametrize(
    "title, message",
    [("   ", "title must not be empty"), ("x" * 101, "title is too long")],
)
async def test_invalid_title(client, world, title, message):
    with pytest.raises(ToolError, match=message):
        await price(client, title)
    assert world.cheapshark_requests == []


async def test_unknown_game(client):
    with pytest.raises(ToolError, match="No game matching 'Zelda 99' was found"):
        await price(client, "Zelda 99")


async def test_game_without_offers(client, world):
    world.games["2"] = {**world.games["2"], "deals": []}
    with pytest.raises(ToolError, match="'Hades' has no current offers"):
        await price(client, "Hades")


async def test_service_unreachable(client, world):
    world.cheapshark_down = True
    with pytest.raises(ToolError, match="unreachable"):
        await price(client, "Celeste")


async def test_rate_limited(client, world):
    world.cheapshark_status = 429
    with pytest.raises(ToolError, match="rate-limiting"):
        await price(client, "Celeste")


async def test_server_error(client, world):
    world.cheapshark_status = 500
    with pytest.raises(ToolError, match="HTTP 500"):
        await price(client, "Celeste")


async def test_throttle_spaces_out_requests():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    cs = CheapSharkClient(CHEAPSHARK, http, min_interval_s=0.3)
    start = time.monotonic()
    await cs.search_games("one")
    await cs.search_games("two")
    assert time.monotonic() - start >= 0.3


async def test_cache_expires_so_prices_stay_fresh():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[])

    cs = CheapSharkClient(CHEAPSHARK, httpx.AsyncClient(transport=httpx.MockTransport(handler)), 0, cache_ttl_s=0.2)
    await cs.search_games("x")
    await cs.search_games("x")
    assert len(calls) == 1  # served from cache
    time.sleep(0.25)
    await cs.search_games("x")
    assert len(calls) == 2  # expired, fetched again


async def test_unreadable_response():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(CheapSharkError, match="unreadable"):
        await CheapSharkClient(CHEAPSHARK, http, 0).search_games("x")
