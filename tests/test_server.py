"""Integration tests for the FastMCP server.

Runs in-process against a 3-comic fixture index by default. Set `XKCD_TEST_URL`
to point at a deployed endpoint to run the same suite against a live server,
OAuth-gated.
"""

from __future__ import annotations


async def test_lists_only_the_search_tool(mcp_client):
    tools = await mcp_client.list_tools()
    assert [t.name for t in tools] == ["search_xkcd"]


async def test_search_ranks_relevant_comic_first(mcp_client):
    result = await mcp_client.call_tool("search_xkcd", {"query": "overton window politics", "k": 3})
    hit = result.data[0]
    assert hit["number"] == 3230
    assert hit["url"] == "https://xkcd.com/3230/"
    assert hit["explanation"]
    assert hit["image_url"]


async def test_search_returns_requested_count(mcp_client):
    result = await mcp_client.call_tool("search_xkcd", {"query": "exploits of a mom sql", "k": 1})
    assert len(result.data) == 1
    assert result.data[0]["number"] == 327
