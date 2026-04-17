from __future__ import annotations

import pytest

from xkcd_search.sources import (
    chunk_comic,
    fetch_explainxkcd,
    fetch_latest_xkcd_number,
    fetch_xkcd,
)


@pytest.mark.vcr
def test_fetch_latest_returns_positive_integer(client):
    latest = fetch_latest_xkcd_number(client)
    assert isinstance(latest, int)
    assert latest > 3000


@pytest.mark.vcr
def test_fetch_xkcd_returns_expected_shape(client):
    meta = fetch_xkcd(3230, client)
    assert meta.number == 3230
    assert meta.title
    assert meta.url == "https://xkcd.com/3230/"
    assert meta.img.startswith("https://imgs.xkcd.com/")


@pytest.mark.vcr
def test_fetch_explainxkcd_returns_wikitext_for_known_article(client):
    article = fetch_explainxkcd(3230, client)
    assert article is not None
    assert article.number == 3230
    assert "==" in article.wikitext


@pytest.mark.vcr
def test_fetch_explainxkcd_returns_none_for_missing_article(client):
    article = fetch_explainxkcd(999999, client)
    assert article is None


@pytest.mark.vcr
def test_chunk_comic_produces_title_and_sections(client):
    xkcd = fetch_xkcd(3230, client)
    article = fetch_explainxkcd(3230, client)
    chunks = chunk_comic(xkcd, article)
    kinds = [c.kind for c in chunks]
    assert "title" in kinds
    assert any(k.startswith("section:") for k in kinds)
    assert all(len(c.text) >= 20 for c in chunks if c.kind != "title")


@pytest.mark.vcr
def test_chunk_comic_without_article_returns_title_plus_transcript(client):
    xkcd = fetch_xkcd(3230, client)
    chunks = chunk_comic(xkcd, article=None)
    kinds = [c.kind for c in chunks]
    assert kinds[0] == "title"
    assert all(k in {"title", "transcript"} for k in kinds)
