from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    return {
        "record_mode": "once",
        "filter_headers": ["user-agent", "authorization"],
        "match_on": ["method", "scheme", "host", "path", "query"],
    }
