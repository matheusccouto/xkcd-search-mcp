from __future__ import annotations

from pathlib import Path

import pytest

from xkcd_search.release import download_latest


@pytest.mark.vcr
def test_download_latest_returns_none_when_no_release_exists(tmp_path: Path, client):
    result = download_latest(tmp_path / "index.sqlite", "matheusccouto/xkcd-search-mcp", client)
    assert result is None
    assert not (tmp_path / "index.sqlite").exists()
