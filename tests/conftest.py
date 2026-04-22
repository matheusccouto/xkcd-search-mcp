from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from fastmcp import Client

from xkcd_search import server
from xkcd_search.builder import (
    fetch_explainxkcd,
    fetch_xkcd,
    new_client,
    open_connection,
    upsert_comic,
)

FIXTURE_NUMBERS = [3230, 353, 327]


@pytest.fixture(scope="session")
def built_index(tmp_path_factory):
    """Build a tiny 3-comic SQLite index once per session.

    No-op when `XKCD_TEST_URL` is set; cloud tests hit the live production index.
    """
    if os.getenv("XKCD_TEST_URL"):
        yield None
        return

    index_path = tmp_path_factory.mktemp("index") / "index.sqlite"
    conn = open_connection(index_path)
    with new_client() as c:
        for number in FIXTURE_NUMBERS:
            xkcd = fetch_xkcd(number, c)
            article = fetch_explainxkcd(number, c)
            upsert_comic(conn, xkcd, article)
    conn.close()

    read_conn = open_connection(index_path, read_only=True)
    original, server._conn = server._conn, read_conn
    yield read_conn
    server._conn = original
    read_conn.close()


@pytest.fixture
async def mcp_client(built_index) -> AsyncIterator[Client]:
    """In-process client by default; hits `XKCD_TEST_URL` when set.

    OAuth only for fastmcp.app hosts (browser consent runs on first use and the
    token is cached under ~/.fastmcp/). Other deployments (HF Spaces, etc.) are
    treated as anonymous HTTPS.
    """
    url = os.getenv("XKCD_TEST_URL")
    if url:
        auth = "oauth" if "fastmcp.app" in url else None
        async with Client(url, auth=auth) as c:
            yield c
    else:
        async with Client(server.mcp) as c:
            yield c
