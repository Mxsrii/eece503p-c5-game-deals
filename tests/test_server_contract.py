"""The assignment's structural rules: exactly three typed, documented tools and one resource."""


async def test_exactly_three_tools(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == {"get_game_price", "send_to_phone", "plan_purchases"}
    for tool in tools.values():
        assert tool.description and len(tool.description) > 80
        assert tool.input_schema["properties"]
        assert tool.output_schema is not None


async def test_required_arguments(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert tools["get_game_price"].input_schema["required"] == ["title"]
    assert set(tools["send_to_phone"].input_schema["required"]) == {"title", "message"}
    assert set(tools["plan_purchases"].input_schema["required"]) == {"wishlist", "budget"}


async def test_one_read_only_resource(client):
    resources = await client.list_resources()
    assert [str(r.uri) for r in resources] == ["notifications://sent"]
    assert resources[0].mime_type == "application/json"
