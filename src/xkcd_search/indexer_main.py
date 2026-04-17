"""Entry point for the daily indexing job (python -m xkcd_search.indexer_main)."""

from __future__ import annotations

import sys
import time

from xkcd_search.config import INDEX_PATH
from xkcd_search.index_builder import iter_known_comics, open_connection, upsert_comic
from xkcd_search.sources import fetch_explainxkcd, fetch_latest_xkcd_number, fetch_xkcd, new_client

REQUEST_DELAY_SECONDS = 0.1

# xkcd 404 famously returns a 404 Not Found by design — skip it.
SKIP_NUMBERS = {404}


def run() -> int:
    conn = open_connection(INDEX_PATH)
    with new_client() as client:
        latest = fetch_latest_xkcd_number(client)
        known = iter_known_comics(conn)
        print(f"latest comic: {latest}; already indexed: {len(known)}", flush=True)

        processed = 0
        for n in range(1, latest + 1):
            if n in SKIP_NUMBERS:
                continue
            if known.get(n) is not None:
                continue

            xkcd = fetch_xkcd(n, client)
            time.sleep(REQUEST_DELAY_SECONDS)
            article = fetch_explainxkcd(n, client)
            time.sleep(REQUEST_DELAY_SECONDS)
            upsert_comic(conn, xkcd, article)

            processed += 1
            if processed % 50 == 0:
                print(f"processed {processed} comics (current: {n})", flush=True)

    final = iter_known_comics(conn)
    with_article = sum(1 for v in final.values() if v is not None)
    gaps = sum(1 for v in final.values() if v is None)
    print(f"done: {len(final)} comics total, {with_article} with article, {gaps} gaps")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
