"""Configuration defaults, overridable via environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir

EMBED_MODEL_NAME: str = os.getenv("XKCD_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM: int = 384

GITHUB_REPO: str = os.getenv("XKCD_GITHUB_REPO", "matheusccouto/xkcd-search-mcp")

INDEX_DIR: Path = Path(os.getenv("XKCD_INDEX_DIR", user_cache_dir("xkcd-search", "matheus")))
INDEX_PATH: Path = INDEX_DIR / "index.sqlite"

USER_AGENT: str = "xkcd-search-mcp (https://github.com/matheusccouto/xkcd-search-mcp)"
