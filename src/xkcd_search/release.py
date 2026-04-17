"""Upload and download the index artifact to / from GitHub Releases.

The daily indexer uploads via the `gh` CLI (preinstalled on ubuntu-latest runners).
The MCP server downloads via the public REST API (60 req/hr/IP, no auth required).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

from xkcd_search.config import USER_AGENT

RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"
ASSET_NAME = "index.sqlite"


@dataclass(frozen=True)
class ReleaseAsset:
    asset_id: int
    download_url: str
    updated_at: str
    size: int


def _fetch_latest_asset(repo: str, client: httpx.Client) -> ReleaseAsset | None:
    """Return the `index.sqlite` asset of the latest release, or None if absent."""
    resp = client.get(RELEASES_API.format(repo=repo))
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            return ReleaseAsset(
                asset_id=int(asset["id"]),
                download_url=str(asset["browser_download_url"]),
                updated_at=str(asset["updated_at"]),
                size=int(asset["size"]),
            )
    return None


def download_latest(
    dest: Path, repo: str, client: httpx.Client | None = None
) -> ReleaseAsset | None:
    """Download the latest `index.sqlite` release asset to `dest`.

    Idempotent: if a sidecar `<dest>.asset_id` file matches the remote asset id,
    the download is skipped. Returns the asset descriptor, or None if no release
    is published yet.
    """
    owned = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0)
    try:
        asset = _fetch_latest_asset(repo, client)
        if asset is None:
            return None

        sidecar = dest.with_suffix(dest.suffix + ".asset_id")
        if (
            dest.exists()
            and sidecar.exists()
            and sidecar.read_text().strip() == str(asset.asset_id)
        ):
            return asset

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with client.stream("GET", asset.download_url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
        tmp.replace(dest)
        sidecar.write_text(str(asset.asset_id))
        return asset
    finally:
        if owned:
            client.close()


def upload_release(path: Path, tag: str, title: str, notes: str) -> None:
    """Create a GitHub release with `path` attached as the `index.sqlite` asset.

    Uses the `gh` CLI which authenticates via the ambient GITHUB_TOKEN in Actions
    or the local gh config otherwise. No secrets are read or logged here.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    subprocess.run(
        ["gh", "release", "create", tag, str(path), "--title", title, "--notes", notes],
        check=True,
    )
