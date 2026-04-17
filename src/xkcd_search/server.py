"""FastMCP server exposing the `search_xkcd` tool.

On startup: pulls the latest `index.sqlite` release asset from GitHub, opens a
read-only connection, and starts a 1-hour poll loop that re-downloads if a new
release is published. The embedding model is loaded lazily on the first query.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
from typing import Any

import sqlite_vec
from fastmcp import FastMCP

from xkcd_search import embeddings
from xkcd_search.config import GITHUB_REPO, INDEX_PATH
from xkcd_search.release import download_latest

POLL_INTERVAL_SECONDS = 3600.0

mcp = FastMCP("xkcd-search")

_conn_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _open_readonly() -> sqlite3.Connection:
    uri = f"file:{INDEX_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _refresh_index() -> None:
    """Download latest release (if newer) and swap the read-only connection."""
    global _conn
    download_latest(INDEX_PATH, GITHUB_REPO)
    if not INDEX_PATH.exists():
        return
    new_conn = _open_readonly()
    with _conn_lock:
        old, _conn = _conn, new_conn
    if old is not None:
        old.close()


def _poll_loop() -> None:
    while True:
        threading.Event().wait(POLL_INTERVAL_SECONDS)
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


def _query(query_text: str, k: int) -> list[tuple[int, float]]:
    from xkcd_search.index_builder import query_top_k

    conn = _ensure_ready()
    vec = embeddings.encode([query_text])[0]
    return query_top_k(conn, vec, k)


def _load_comic_row(number: int, conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT number, title, url, image_url, alt_text, transcript, explanation
        FROM comics WHERE number = ?
        """,
        (number,),
    ).fetchone()
    number, title, url, image_url, alt_text, transcript, explanation = row
    return {
        "number": int(number),
        "title": str(title),
        "url": str(url),
        "image_url": image_url,
        "alt_text": alt_text,
        "transcript": transcript,
        "explanation": explanation,
    }


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
    (CC BY-SA 3.0 — attribution required).
    """
    k = max(1, min(int(k), 20))
    conn = _ensure_ready()
    hits = _query(query, k)
    results: list[dict[str, Any]] = []
    for number, similarity in hits:
        comic = _load_comic_row(number, conn)
        out: dict[str, Any] = {
            "number": comic["number"],
            "title": comic["title"],
            "url": comic["url"],
            "similarity": round(float(similarity), 4),
        }
        if include_image_url:
            out["image_url"] = comic["image_url"]
        if include_alt_text:
            out["alt_text"] = comic["alt_text"]
        if include_transcript:
            out["transcript"] = comic["transcript"]
        if include_explanation:
            out["explanation"] = comic["explanation"]
        results.append(out)
    return results


def _start_background_poll() -> None:
    thread = threading.Thread(target=_poll_loop, daemon=True, name="xkcd-index-poller")
    thread.start()


def bootstrap() -> None:
    """Fetch the latest release and start the background poller.

    Safe to call multiple times; the poll thread is started once per process.
    """
    _refresh_index()
    if not any(t.name == "xkcd-index-poller" for t in threading.enumerate()):
        _start_background_poll()


_AUTO_BOOTSTRAP = "pytest" not in sys.modules and os.getenv("XKCD_SKIP_BOOTSTRAP") != "1"

if _AUTO_BOOTSTRAP:
    bootstrap()


if __name__ == "__main__":
    mcp.run()
