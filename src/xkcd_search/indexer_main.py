"""Entry point for the daily indexing job (python -m xkcd_search.indexer_main)."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

import httpx

from xkcd_search.config import INDEX_PATH
from xkcd_search.index_builder import iter_known_comics, open_connection, upsert_comic
from xkcd_search.sources import fetch_explainxkcd, fetch_latest_xkcd_number, fetch_xkcd, new_client

REQUEST_DELAY_SECONDS = 0.1

# Comic 404 returns HTTP 404 by design (the joke); the fetcher would raise on it.
SKIP_NUMBERS = {404}

RETRY_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


def _with_retry[T](fn: Callable[[], T], *, label: str) -> T:
    """Retry a fetch on transient HTTP errors with exponential backoff.

    Retries 5xx / 429 / connect timeouts. Lets 4xx (other than 429) and
    programming errors surface immediately.
    """
    delay = 1.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS:
                raise
            print(
                f"retry {attempt}/{MAX_ATTEMPTS} for {label}: "
                f"HTTP {exc.response.status_code}, sleeping {delay:.1f}s",
                flush=True,
            )
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            print(
                f"retry {attempt}/{MAX_ATTEMPTS} for {label}: "
                f"{type(exc).__name__}, sleeping {delay:.1f}s",
                flush=True,
            )
        time.sleep(delay)
        delay = min(delay * 2, 30.0)
    raise RuntimeError("unreachable")


def _limit_from_env() -> int | None:
    raw = os.getenv("XKCD_INDEXER_LIMIT", "").strip()
    if not raw:
        return None
    return int(raw)


def run() -> int:
    limit = _limit_from_env()
    conn = open_connection(INDEX_PATH)
    with new_client() as client:
        latest = _with_retry(lambda: fetch_latest_xkcd_number(client), label="latest")
        known = iter_known_comics(conn)
        print(
            f"latest comic: {latest}; already indexed: {len(known)}"
            + (f"; limit: {limit}" if limit else ""),
            flush=True,
        )

        processed = 0
        for n in range(1, latest + 1):
            if limit is not None and processed >= limit:
                print(f"reached limit={limit}; stopping at n={n}", flush=True)
                break
            if n in SKIP_NUMBERS:
                continue
            if known.get(n) is not None:
                continue

            xkcd = _with_retry(lambda n=n: fetch_xkcd(n, client), label=f"xkcd {n}")
            time.sleep(REQUEST_DELAY_SECONDS)
            article = _with_retry(lambda n=n: fetch_explainxkcd(n, client), label=f"explain {n}")
            time.sleep(REQUEST_DELAY_SECONDS)
            upsert_comic(conn, xkcd, article)

            processed += 1
            if processed % 50 == 0:
                print(f"processed {processed} comics (current: {n})", flush=True)

    total = conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
    with_article = conn.execute(
        "SELECT COUNT(*) FROM comics WHERE explained_at IS NOT NULL"
    ).fetchone()[0]
    gaps = total - with_article
    print(f"done: {total} comics total, {with_article} with article, {gaps} gaps")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
