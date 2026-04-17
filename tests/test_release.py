from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from xkcd_search.release import download_latest


@pytest.fixture
def client():
    with httpx.Client(timeout=10.0) as c:
        yield c


@pytest.mark.vcr
def test_download_latest_returns_none_when_no_release_exists(tmp_path: Path, client):
    # The repo exists but has no releases — the API returns 404 on /releases/latest.
    result = download_latest(tmp_path / "index.sqlite", "matheusccouto/xkcd-search-mcp", client)
    assert result is None
    assert not (tmp_path / "index.sqlite").exists()
