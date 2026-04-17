from __future__ import annotations

import pytest

from xkcd_search.sources import new_client


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    return {
        "record_mode": "once",
        "filter_headers": ["user-agent", "authorization"],
        "match_on": ["method", "scheme", "host", "path", "query"],
    }


@pytest.fixture
def client():
    with new_client() as c:
        yield c


@pytest.fixture
def fixture_numbers() -> list[int]:
    """Thematically distinct comics: Overton window, Python, Exploits of a Mom."""
    return [3230, 353, 327]
