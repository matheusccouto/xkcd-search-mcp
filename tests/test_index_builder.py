from __future__ import annotations

from pathlib import Path

import pytest

from xkcd_search import embeddings
from xkcd_search.index_builder import (
    iter_known_comics,
    open_connection,
    query_top_k,
    upsert_comic,
)
from xkcd_search.sources import fetch_explainxkcd, fetch_xkcd


@pytest.fixture
def index_path(tmp_path: Path) -> Path:
    return tmp_path / "index.sqlite"


@pytest.mark.vcr
def test_upsert_and_known_state(index_path, client):
    conn = open_connection(index_path)
    xkcd = fetch_xkcd(3230, client)
    article = fetch_explainxkcd(3230, client)
    upsert_comic(conn, xkcd, article)

    known = iter_known_comics(conn)
    assert set(known.keys()) == {3230}
    assert known[3230] is not None
    conn.close()


@pytest.mark.vcr
def test_gap_stored_when_article_missing(index_path, client):
    conn = open_connection(index_path)
    xkcd = fetch_xkcd(3230, client)
    upsert_comic(conn, xkcd, article=None)

    known = iter_known_comics(conn)
    assert known[3230] is None
    conn.close()


@pytest.mark.vcr
def test_top_k_ranks_semantically_closest_comic_first(index_path, client, fixture_numbers):
    conn = open_connection(index_path)
    for number in fixture_numbers:
        xkcd = fetch_xkcd(number, client)
        article = fetch_explainxkcd(number, client)
        upsert_comic(conn, xkcd, article)

    query_vec = embeddings.encode(["overton window politics"])[0]
    hits = query_top_k(conn, query_vec, k=3)
    assert hits[0][0] == 3230
    assert hits[0][1] > 0.3
    assert {n for n, _ in hits} <= set(fixture_numbers)
    conn.close()
