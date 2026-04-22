"""FastMCP server exposing `search_xkcd`.

On boot, downloads the latest `index.sqlite` GitHub Release asset and opens a
read-only SQLite connection. No polling: the nightly indexer triggers a redeploy
(by pushing an empty commit), which restarts this process and re-downloads the
fresh artifact.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from typing import Any

import httpx
from fastmcp import FastMCP

from xkcd_search.builder import INDEX_PATH, encode, open_connection, query_top_k

GITHUB_REPO = "matheusccouto/xkcd-search-mcp"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

mcp = FastMCP("xkcd-search")
_conn: sqlite3.Connection | None = None


def _download_index() -> None:
    """Fetch the latest `index.sqlite` Release asset into INDEX_PATH."""
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(RELEASES_API)
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            if asset.get("name") == "index.sqlite":
                INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
                with client.stream("GET", asset["browser_download_url"]) as r:
                    r.raise_for_status()
                    with INDEX_PATH.open("wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                return
        raise RuntimeError(f"no 'index.sqlite' asset in latest release of {GITHUB_REPO}")


@mcp.tool
def search_xkcd(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Semantic search over xkcd comics, ranked by relevance to `query`.

    Returns up to `k` comics, each with `number`, `title`, `url`, `image_url`,
    `alt_text`, `transcript`, and `explanation`. Cite the `url` when referencing
    a comic; explanations come from explainxkcd.com (CC BY-SA 3.0).
    """
    assert _conn is not None, "index not loaded"
    k = max(1, min(int(k), 20))
    numbers = query_top_k(_conn, encode([query])[0], k)
    if not numbers:
        return []
    placeholders = ",".join("?" * len(numbers))
    rows = _conn.execute(
        f"SELECT number, title, url, image_url, alt_text, transcript, explanation "
        f"FROM comics WHERE number IN ({placeholders})",
        numbers,
    ).fetchall()
    by_number = {int(r[0]): r for r in rows}
    return [
        {
            "number": n,
            "title": by_number[n][1],
            "url": by_number[n][2],
            "image_url": by_number[n][3],
            "alt_text": by_number[n][4],
            "transcript": by_number[n][5],
            "explanation": by_number[n][6],
        }
        for n in numbers
    ]


if "pytest" not in sys.modules and os.getenv("XKCD_SKIP_BOOTSTRAP") != "1":
    if not INDEX_PATH.exists():
        _download_index()
    _conn = open_connection(INDEX_PATH, read_only=True)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        path="/mcp",
    )
