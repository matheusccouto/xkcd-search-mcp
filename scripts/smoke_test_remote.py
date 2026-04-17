"""End-to-end smoke test against the deployed FastMCP Cloud endpoint.

Run from your laptop (the browser callback lands on localhost):

    uv run python scripts/smoke_test_remote.py

On first run a browser opens for Horizon (Prefect) login. The token is cached
under ~/.fastmcp/ so subsequent runs reuse it.
"""

from __future__ import annotations

import asyncio
import sys

from fastmcp import Client

SERVER_URL = "https://xkcd-search.fastmcp.app/mcp"


async def main() -> int:
    async with Client(SERVER_URL, auth="oauth") as client:
        tools = await client.list_tools()
        tool_names = sorted(t.name for t in tools)
        print(f"tools: {tool_names}")
        assert tool_names == ["get_comic", "search_xkcd"], f"unexpected tools: {tool_names}"

        result = await client.call_tool(
            "search_xkcd",
            {"query": "overton window politics", "k": 3, "include_explanation": False},
        )
        hits = result.data
        print("\nsearch_xkcd('overton window politics', k=3):")
        for h in hits:
            print(f"  #{h['number']:>4} sim={h['similarity']:.3f}  {h['title']}")
        assert any(h["number"] == 3230 for h in hits), "expected #3230 Overton in top 3"

        result = await client.call_tool(
            "search_xkcd",
            {"query": "sql injection bobby tables", "k": 3, "include_explanation": False},
        )
        hits = result.data
        print("\nsearch_xkcd('sql injection bobby tables', k=3):")
        for h in hits:
            print(f"  #{h['number']:>4} sim={h['similarity']:.3f}  {h['title']}")
        assert any(h["number"] == 327 for h in hits), "expected #327 Exploits of a Mom in top 3"

        result = await client.call_tool("get_comic", {"number": 353, "include_explanation": False})
        comic = result.data
        print(f"\nget_comic(353): #{comic['number']}  {comic['title']}  {comic['url']}")
        assert comic["number"] == 353 and comic["title"].lower() == "python"

        result = await client.call_tool("get_comic", {"number": 404, "include_explanation": False})
        print(f"get_comic(404): {result.data}  (expected None — comic 404 is skipped)")
        assert result.data is None

        result = await client.call_tool(
            "get_comic", {"number": 999999, "include_explanation": False}
        )
        print(f"get_comic(999999): {result.data}  (expected None)")
        assert result.data is None

    print("\nOK: all assertions passed against the live endpoint")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
