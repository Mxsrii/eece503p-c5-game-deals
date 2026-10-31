import time

import httpx
import pytest
from fastmcp.exceptions import ToolError

from toolkit.cheapshark import CheapSharkClient, CheapSharkError
from toolkit.config import USER_AGENT

from .conftest import CHEAPSHARK, game


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
    assert out["other_matches"] == [
        {"game_id": "5", "title": "Hollow Knight: Silksong", "cheapest_price": 19.99, "kind": "other"}
    ]


async def test_inexact_match_carries_a_warning(client):
    out = await price(client, "hollow")
    assert out["exact_match"] is False
    assert out["title"] == "Hollow Knight: Silksong"
    assert out["searched_for"] == "hollow"
    assert out["warning"] == (
        "'hollow' matched 'Hollow Knight: Silksong', which may be a different game. "
        "Also found: Hollow Knight. Ask which one they mean."
    )


async def test_franchise_search_lists_every_match_with_prices(client, world):
    # Like the real "spongebob" search: one query, many different games.
    world.search["spongebob"] = [
        {"gameID": f"9{i}", "external": f"SpongeBob Game {i}", "cheapest": f"{i + 1}.99"} for i in range(6)
    ]
    world.games["90"] = world.games["1"]  # details for the first hit
    out = await price(client, "spongebob")
    assert out["exact_match"] is False
    assert [m["title"] for m in out["other_matches"]] == [f"SpongeBob Game {i}" for i in range(1, 6)]
    assert out["other_matches"][0]["cheapest_price"] == 2.99
    assert "Also found: SpongeBob Game 1, SpongeBob Game 2, SpongeBob Game 3 and 2 more." in out["warning"]


def _editions_world(world):
    """Like the real "Red Dead Redemption 2" search: base game, a fuller edition, an add-on."""
    world.games["6"] = game("6", "Red Dead Redemption 2", [("1", 13.46, 59.99)], all_time_low=9.89)
    world.games["7"] = game("7", "Red Dead Redemption 2: Ultimate Edition", [("1", 17.96, 99.99)], all_time_low=14.0)
    world.games["8"] = game("8", "Red Dead Redemption 2 - Outfit Pack DLC", [("1", 1.99, 4.99)], all_time_low=0.99)
    hits = [
        {"gameID": "8", "external": "Red Dead Redemption 2 - Outfit Pack DLC", "cheapest": "1.99"},
        {"gameID": "7", "external": "Red Dead Redemption 2: Ultimate Edition", "cheapest": "17.96"},
        {"gameID": "6", "external": "Red Dead Redemption 2", "cheapest": "13.46"},
    ]
    world.search["red dead redemption 2"] = hits
    world.search["red dead"] = hits


async def test_editions_and_add_ons_are_labelled(client, world):
    _editions_world(world)
    out = await price(client, "Red Dead Redemption 2")
    assert out["title"] == "Red Dead Redemption 2" and out["price"] == 13.46
    kinds = {m["title"]: m["kind"] for m in out["other_matches"]}
    assert kinds == {
        "Red Dead Redemption 2 - Outfit Pack DLC": "add-on",
        "Red Dead Redemption 2: Ultimate Edition": "edition",
    }
    assert out["edition_note"].startswith(
        "Red Dead Redemption 2: Ultimate Edition is only $4.50 more ($17.96)"
    )


async def test_vague_search_never_picks_an_add_on(client, world):
    _editions_world(world)
    out = await price(client, "red dead")  # the search ranks the $1.99 DLC first
    assert out["title"] == "Red Dead Redemption 2: Ultimate Edition"
    assert out["exact_match"] is False
    assert "Outfit Pack" not in out["warning"]  # add-ons aren't offered as alternatives


async def test_no_edition_note_without_editions(client):
    assert (await price(client, "Celeste"))["edition_note"] is None


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
