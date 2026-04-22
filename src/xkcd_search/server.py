"""FastMCP server exposing `search_xkcd`.

On boot, downloads the latest `index.sqlite` GitHub Release asset and opens a
read-only SQLite connection. No polling: the nightly indexer publishes a new
Release and calls the HF Spaces restart API, which restarts this process and
re-downloads the fresh artifact.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastmcp import FastMCP

from xkcd_search.builder import INDEX_PATH, encode, new_client, open_connection, query_top_k

GITHUB_REPO = "matheusccouto/xkcd-search-mcp"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

mcp = FastMCP("xkcd-search")
_conn: sqlite3.Connection | None = None


def _download_index() -> None:
    """Fetch the latest `index.sqlite` Release asset into INDEX_PATH."""
    with new_client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(RELEASES_API)
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            if asset.get("name") == "index.sqlite":
                INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = INDEX_PATH.with_suffix(".tmp")
                with client.stream("GET", asset["browser_download_url"]) as r:
                    r.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                tmp.rename(INDEX_PATH)
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
    sql = (
        "SELECT number, title, url, image_url, alt_text, transcript, explanation "
        f"FROM comics WHERE number IN ({placeholders})"
    )
    rows = _conn.execute(sql, numbers).fetchall()
    by_number = {r["number"]: r for r in rows}
    return [dict(by_number[n]) for n in numbers if n in by_number]


LANDING_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>xkcd-search MCP Server</title>
    <style>
        body {
    font-family: system-ui, sans-serif;
    max-width: 800px;
    margin: 40px auto;
    padding: 20px;
}
        h1 { color: #1a1a2e; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
        pre { background: #f4f4f4; padding: 16px; border-radius: 8px; overflow-x: auto; }
        .endpoint { color: #e94560; font-weight: bold; }
        a { color: #0f3460; }
    </style>
</head>
<body>
    <h1>🔎 xkcd-search MCP Server</h1>
    <p>Semantic search for xkcd comics via the Model Context Protocol.</p>
    
    <h2>MCP Endpoint</h2>
    <p><code class="endpoint">https://couto-xkcd-search.hf.space/mcp</code></p>
    
    <h2>How to Connect</h2>
    <p>Add to your MCP client configuration (Claude Desktop, Cursor, VS Code, etc.):</p>
    <pre>
{
  "mcpServers": {
    "xkcd-search": {
      "url": "https://couto-xkcd-search.hf.space/mcp"
    }
  }
}
    </pre>
    
    <h2>Available Tool</h2>
    <p><code>search_xkcd(query: str, k: int = 5)</code> - Returns top-K relevant comics.</p>
    
    <h2>More Info</h2>
    <p><a href="https://github.com/matheusccouto/xkcd-search-mcp">GitHub Repository</a></p>
    
    <hr>
    <p><small>Data from explainxkcd.com (CC BY-SA 3.0). Comic images by Randall Munroe.</small></p>
</body>
</html>
"""


def _is_browser(request: Request) -> bool:
    """Detect if the request is from a browser (not an MCP client)."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/xhtml+xml" in accept


app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Serve landing page for browsers, 406 for MCP clients."""
    if _is_browser(request):
        return LANDING_HTML
    return HTMLResponse(content="", status_code=406)


app.mount("/mcp", mcp.http_app(transport="streamable-http"))


if "pytest" not in sys.modules and os.getenv("XKCD_SKIP_BOOTSTRAP") != "1":
    if not INDEX_PATH.exists():
        _download_index()
    _conn = open_connection(INDEX_PATH, read_only=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
