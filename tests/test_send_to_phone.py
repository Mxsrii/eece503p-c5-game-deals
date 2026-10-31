import json
from dataclasses import replace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server

from .conftest import install


async def send(client, **args):
    return (await client.call_tool("send_to_phone", args)).structured_content


async def sent_log(client) -> list[dict]:
    contents = await client.read_resource("notifications://sent")
    return json.loads(contents[0].text)


async def test_sends_and_logs(client, world):
    links = {"Buy Celeste": "https://example.com/a", "Buy Hades": "https://example.com/b"}
    out = await send(client, title="Deals", message="Celeste $4.99", links=links)

    body = world.ntfy_bodies()[0]
    assert body["topic"] == "test-topic" and body["title"] == "Deals"
    assert body["click"] == "https://example.com/a"  # tap opens the first link
    assert [a["label"] for a in body["actions"]] == ["Buy Celeste", "Buy Hades"]

    assert out["id"] == 1 and out["links"] == links
    assert await sent_log(client) == [out]


async def test_links_are_optional(client, world):
    await send(client, title="Hi", message="No links")
    body = world.ntfy_bodies()[0]
    assert body["actions"] == [] and "click" not in body


async def test_every_call_sends_again(client, world):
    await send(client, title="A", message="x")
    await send(client, title="A", message="x")
    assert len(world.ntfy_requests) == 2
    assert [n["id"] for n in await sent_log(client)] == [2, 1]  # newest first


# ------------------------------------------------------------ failure cases


@pytest.mark.parametrize(
    "args, message",
    [
        ({"title": " ", "message": "x"}, "title must be 1 to 100"),
        ({"title": "x" * 101, "message": "x"}, "title must be 1 to 100"),
        ({"title": "t", "message": ""}, "message must be 1 to 2000"),
        ({"title": "t", "message": "x", "links": {str(i): "https://a.b" for i in range(4)}}, "At most 3 links"),
        ({"title": "t", "message": "x", "links": {"Bad": "javascript:alert(1)"}}, "must be an http"),
        ({"title": "t", "message": "x", "links": {"": "https://a.b"}}, "label must be 1 to 40"),
    ],
)
async def test_invalid_input_sends_nothing(client, world, args, message):
    with pytest.raises(ToolError, match=message):
        await send(client, **args)
    assert world.ntfy_requests == []
    assert await sent_log(client) == []


async def test_missing_topic_sends_nothing(world, settings):
    install(world, replace(settings, ntfy_topic=None))
    async with Client(server.mcp) as c:
        with pytest.raises(ToolError, match="set NTFY_TOPIC"):
            await send(c, title="t", message="x")
    server.set_services(None)
    assert world.ntfy_requests == []


@pytest.mark.parametrize("status, message", [(500, "HTTP 500.*Nothing was sent"), (429, "rate-limiting")])
async def test_rejected_is_not_logged(client, world, status, message):
    world.ntfy_status = status
    with pytest.raises(ToolError, match=message):
        await send(client, title="t", message="x")
    assert await sent_log(client) == []


async def test_unreachable_is_not_logged(client, world):
    world.ntfy_down = True
    with pytest.raises(ToolError, match="unreachable.*Nothing was sent"):
        await send(client, title="t", message="x")
    assert await sent_log(client) == []
