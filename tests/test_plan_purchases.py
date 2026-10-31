import pytest
from fastmcp.exceptions import ToolError


async def plan(client, **args):
    return (await client.call_tool("plan_purchases", args)).structured_content


def names(items):
    return [i["game"]["title"] for i in items]


async def test_full_plan_is_sent(client, world):
    out = await plan(client, wishlist=["Celeste", "Hades", "Hollow Knight"], budget=20)

    assert names(out["buy"]) == ["Celeste", "Hades"]
    assert out["total_cost"] == 17.48 and out["total_saved"] == 27.5 and out["budget_left"] == 2.52
    assert names(out["wait"]) == ["Hollow Knight"]
    assert "has been as low as $2.99" in out["wait"][0]["reason"]

    body = world.ntfy_bodies()[0]
    assert body["title"] == "Buy 2 games for $17.48 (save $27.50)"
    assert "Buy Celeste: $4.99 at GOG" in body["message"]
    assert "Wait on Hollow Knight: $14.99 now" in body["message"]
    assert [a["label"] for a in body["actions"]] == ["Buy Celeste", "Buy Hades"]
    assert out["notification"]["id"] == 1


async def test_tight_budget_keeps_the_biggest_saving(client):
    out = await plan(client, wishlist=["Celeste", "Hades"], budget=17, send=False)
    assert names(out["buy"]) == ["Celeste"]
    assert names(out["over_budget"]) == ["Hades"]


async def test_coordinates_the_other_two_tools(client, world):
    await plan(client, wishlist=["Celeste", "Hades"], budget=50)
    paths = [(r.url.path.rsplit("/", 1)[-1], dict(r.url.params)) for r in world.cheapshark_requests]
    assert ("games", {"title": "Celeste", "limit": "10"}) in paths
    assert ("games", {"title": "Hades", "limit": "10"}) in paths
    assert len(world.ntfy_requests) == 1  # one notification for the whole plan


async def test_preview_sends_nothing(client, world):
    out = await plan(client, wishlist=["Celeste"], budget=10, send=False)
    assert names(out["buy"]) == ["Celeste"]
    assert out["notification"] is None
    assert world.ntfy_requests == []


async def test_nothing_worth_buying_sends_nothing(client, world):
    out = await plan(client, wishlist=["Hollow Knight"], budget=50)
    assert out["buy"] == [] and names(out["wait"]) == ["Hollow Knight"]
    assert out["notification"] is None
    assert world.ntfy_requests == []


async def test_unknown_titles_are_skipped_and_reported(client):
    out = await plan(client, wishlist=["Celeste", "Zelda 99"], budget=10, send=False)
    assert names(out["buy"]) == ["Celeste"]
    assert out["not_found"] == ["Zelda 99"]


async def test_duplicates_are_removed(client, world):
    out = await plan(client, wishlist=["Celeste", "celeste ", "CELESTE"], budget=50, send=False)
    assert names(out["buy"]) == ["Celeste"]


# ------------------------------------------------------------ failure cases


@pytest.mark.parametrize(
    "args, message",
    [
        ({"wishlist": [], "budget": 10}, "1 to 10 game titles"),
        ({"wishlist": ["  "], "budget": 10}, "1 to 10 game titles"),
        ({"wishlist": [f"Game {i}" for i in range(11)], "budget": 10}, "1 to 10 game titles"),
        ({"wishlist": ["Celeste"], "budget": 0}, "budget must be more than 0"),
        ({"wishlist": ["Celeste"], "budget": 5000}, "at most 1000"),
    ],
)
async def test_invalid_input_does_nothing(client, world, args, message):
    with pytest.raises(ToolError, match=message):
        await plan(client, **args)
    assert world.cheapshark_requests == [] and world.ntfy_requests == []


async def test_no_game_found_at_all(client, world):
    with pytest.raises(ToolError, match="None of the games were found: Zelda 99, Mario 42. Nothing was sent"):
        await plan(client, wishlist=["Zelda 99", "Mario 42"], budget=10)
    assert world.ntfy_requests == []


async def test_price_service_down_sends_nothing(client, world):
    world.cheapshark_down = True
    with pytest.raises(ToolError, match="unreachable"):
        await plan(client, wishlist=["Celeste"], budget=10)
    assert world.ntfy_requests == []


async def test_send_failure_names_the_plan(client, world):
    world.ntfy_status = 500
    with pytest.raises(ToolError, match="Planned to buy Celeste but could not send the list: .*HTTP 500"):
        await plan(client, wishlist=["Celeste"], budget=10)
