from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastmcp import Client

from xkcd_search import server
from xkcd_search.index_builder import open_connection, upsert_comic
from xkcd_search.sources import fetch_explainxkcd, fetch_xkcd, new_client


@pytest.fixture
def built_index(tmp_path: Path, monkeypatch, fixture_numbers):
    index_path = tmp_path / "index.sqlite"
    conn = open_connection(index_path)
    with new_client() as client:
        for number in fixture_numbers:
            xkcd = fetch_xkcd(number, client)
            article = fetch_explainxkcd(number, client)
            upsert_comic(conn, xkcd, article)
    conn.close()

    read_conn = open_connection(index_path, read_only=True)
    monkeypatch.setattr(server, "_conn", read_conn)
    yield
    read_conn.close()
    monkeypatch.setattr(server, "_conn", None)


@pytest.mark.vcr
def test_search_xkcd_ranks_relevant_comic_first(built_index):
    async def run() -> list[dict]:
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "search_xkcd", {"query": "overton window politics", "k": 3}
            )
            return result.data

    hits = asyncio.run(run())
    assert hits[0]["number"] == 3230
    assert hits[0]["url"] == "https://xkcd.com/3230/"
    assert hits[0]["similarity"] > 0.3
    assert "explanation" in hits[0]
    assert "transcript" not in hits[0]


@pytest.mark.vcr
def test_search_xkcd_respects_field_flags(built_index):
    async def run() -> list[dict]:
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "search_xkcd",
                {
                    "query": "sql injection",
                    "k": 1,
                    "include_transcript": True,
                    "include_explanation": False,
                    "include_image_url": False,
                    "include_alt_text": False,
                },
            )
            return result.data

    hits = asyncio.run(run())
    assert hits[0]["number"] == 327
    assert "transcript" in hits[0]
    assert "explanation" not in hits[0]
    assert "image_url" not in hits[0]
    assert "alt_text" not in hits[0]


def test_get_comic_returns_indexed_comic(built_index):
    async def run() -> dict:
        async with Client(server.mcp) as client:
            result = await client.call_tool("get_comic", {"number": 327})
            return result.data

    comic = asyncio.run(run())
    assert comic["number"] == 327
    assert comic["url"] == "https://xkcd.com/327/"
    assert "similarity" not in comic
    assert "transcript" in comic
    assert "explanation" in comic


def test_get_comic_returns_none_for_missing_number(built_index):
    async def run():
        async with Client(server.mcp) as client:
            result = await client.call_tool("get_comic", {"number": 999999})
            return result.data

    assert asyncio.run(run()) is None
