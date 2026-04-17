"""FastMCP server exposing the `search_xkcd` tool.

Downloads the latest `index.sqlite` release asset on first query, opens a
read-only connection, and starts a 1-hour poll loop that swaps the connection
only when a newer asset is published. The embedding model is loaded lazily on
the first query.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from typing import Any

from fastmcp import FastMCP

from xkcd_search import embeddings
from xkcd_search.config import GITHUB_REPO, INDEX_PATH
from xkcd_search.index_builder import open_connection, query_top_k
from xkcd_search.release import download_latest

POLL_INTERVAL_SECONDS = 3600.0

mcp = FastMCP("xkcd-search")

_conn_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_current_asset_id: int | None = None


def _refresh_index() -> None:
    """Download the latest release and swap the read-only connection if it changed."""
    global _conn, _current_asset_id
    asset = download_latest(INDEX_PATH, GITHUB_REPO)
    if asset is None or not INDEX_PATH.exists():
        return
    if asset.asset_id == _current_asset_id and _conn is not None:
        return
    new_conn = open_connection(INDEX_PATH, read_only=True)
    with _conn_lock:
        old, _conn = _conn, new_conn
        _current_asset_id = asset.asset_id
    if old is not None:
        old.close()


def _poll_loop() -> None:
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        _refresh_index()


def _ensure_ready() -> sqlite3.Connection:
    with _conn_lock:
        if _conn is not None:
            return _conn
    _refresh_index()
    with _conn_lock:
        if _conn is None:
            raise RuntimeError(
                f"no index artifact available for {GITHUB_REPO}; the daily indexer "
                "workflow must publish a release named `index.sqlite` before the "
                "server can answer queries."
            )
        return _conn


def _fetch_comics(numbers: list[int], conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    if not numbers:
        return {}
    placeholders = ",".join("?" * len(numbers))
    rows = conn.execute(
        f"""
        SELECT number, title, url, image_url, alt_text, transcript, explanation
        FROM comics WHERE number IN ({placeholders})
        """,
        numbers,
    ).fetchall()
    return {
        int(row[0]): {
            "number": int(row[0]),
            "title": str(row[1]),
            "url": str(row[2]),
            "image_url": row[3],
            "alt_text": row[4],
            "transcript": row[5],
            "explanation": row[6],
        }
        for row in rows
    }


def _project_fields(
    comic: dict[str, Any],
    *,
    include_image_url: bool,
    include_alt_text: bool,
    include_transcript: bool,
    include_explanation: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "number": comic["number"],
        "title": comic["title"],
        "url": comic["url"],
    }
    if include_image_url:
        out["image_url"] = comic["image_url"]
    if include_alt_text:
        out["alt_text"] = comic["alt_text"]
    if include_transcript:
        out["transcript"] = comic["transcript"]
    if include_explanation:
        out["explanation"] = comic["explanation"]
    return out


@mcp.tool
def search_xkcd(
    query: str,
    k: int = 5,
    include_transcript: bool = False,
    include_explanation: bool = True,
    include_image_url: bool = True,
    include_alt_text: bool = True,
) -> list[dict[str, Any]]:
    """Semantic search over xkcd comics, ranked by relevance to `query`.

    Every result always includes `number`, `title`, `url`, and `similarity`
    (cosine similarity in [0, 1], higher is closer). Additional fields are
    opt-in via the boolean flags so the caller can trade response size for
    context. The `url` points to xkcd.com; cite it when referencing a comic.
    The `explanation` field, when included, is the raw explainxkcd wikitext
    (CC BY-SA 3.0: attribution required).
    """
    k = max(1, min(int(k), 20))
    conn = _ensure_ready()
    vec = embeddings.encode([query])[0]
    hits = query_top_k(conn, vec, k)
    comics = _fetch_comics([number for number, _ in hits], conn)

    results: list[dict[str, Any]] = []
    for number, similarity in hits:
        out = _project_fields(
            comics[number],
            include_image_url=include_image_url,
            include_alt_text=include_alt_text,
            include_transcript=include_transcript,
            include_explanation=include_explanation,
        )
        out["similarity"] = round(float(similarity), 4)
        results.append(out)
    return results


@mcp.tool
def get_comic(
    number: int,
    include_transcript: bool = True,
    include_explanation: bool = True,
    include_image_url: bool = True,
    include_alt_text: bool = True,
) -> dict[str, Any] | None:
    """Fetch a single xkcd comic by its number. Returns `None` if not indexed.

    Use this when the caller already knows the comic number (e.g. "xkcd 353").
    For text-similarity lookups, use `search_xkcd`. The `url` points to
    xkcd.com; cite it when referencing a comic. The `explanation` field, when
    included, is the raw explainxkcd wikitext (CC BY-SA 3.0: attribution
    required).
    """
    conn = _ensure_ready()
    comic = _fetch_comics([int(number)], conn).get(int(number))
    if comic is None:
        return None
    return _project_fields(
        comic,
        include_image_url=include_image_url,
        include_alt_text=include_alt_text,
        include_transcript=include_transcript,
        include_explanation=include_explanation,
    )


def bootstrap() -> None:
    """Fetch the latest release and start the background poller.

    Safe to call multiple times; the poll thread is started once per process.
    Call from the production entrypoint; tests should skip this and inject
    `_conn` directly.
    """
    _refresh_index()
    if not any(t.name == "xkcd-index-poller" for t in threading.enumerate()):
        threading.Thread(target=_poll_loop, daemon=True, name="xkcd-index-poller").start()


_AUTO_BOOTSTRAP = "pytest" not in sys.modules and os.getenv("XKCD_SKIP_BOOTSTRAP") != "1"

if _AUTO_BOOTSTRAP:
    bootstrap()


if __name__ == "__main__":
    mcp.run()
