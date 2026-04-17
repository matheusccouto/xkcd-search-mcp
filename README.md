# xkcd-search-mcp

![status](https://img.shields.io/badge/status-WIP-yellow)

Semantic search for xkcd comics, served over the Model Context Protocol. Given a
natural-language prompt, the `search_xkcd` tool returns the top-K most relevant
comics from the full xkcd archive, indexed daily against the explainxkcd.com
wiki.

## Connect

The public MCP endpoint:

```
https://xkcd-search.fastmcp.app/mcp
```

Point any MCP client (Claude Desktop, mcp-inspector, Cursor, etc.) at that URL.

See [Hosting](#hosting) for notes on the current authentication situation on
FastMCP Cloud and the fallback plan.

## The tools

```python
search_xkcd(
    query: str,
    k: int = 5,
    include_transcript: bool = False,
    include_explanation: bool = True,
    include_image_url: bool = True,
    include_alt_text: bool = True,
) -> list[dict]
```

Semantic top-K lookup. Every result includes `number`, `title`, `url`, and
`similarity`. The boolean flags let the caller opt into heavier fields per
call rather than baking the choice into the server.

```python
get_comic(
    number: int,
    include_transcript: bool = True,
    include_explanation: bool = True,
    include_image_url: bool = True,
    include_alt_text: bool = True,
) -> dict | None
```

Direct lookup by comic number. Returns `None` if the comic is not in the
index (either unpublished or skipped, like comic 404). Useful when the caller
already knows which comic it wants.

## How it works

1. A daily GitHub Actions job (`.github/workflows/index-daily.yml`) fetches
   every xkcd comic's JSON and, when available, its explainxkcd wikitext.
2. Each comic is split into a title chunk, a transcript chunk, and one chunk
   per explainxkcd `== Section ==`. Long sections are split on paragraph breaks.
3. Chunks are embedded with `BAAI/bge-small-en-v1.5` (384-dim, L2-normalized)
   and written into a single `index.sqlite` file backed by `sqlite-vec`.
4. The artifact is published as the `index.sqlite` asset on the repo's latest
   GitHub Release.
5. The FastMCP server downloads that asset on startup and polls hourly for a
   newer one. Queries run locally against the in-memory SQLite file.

There is no hosted database and no API key anywhere in the stack.

## Local development

```bash
uv sync
uv run pytest                                 # replays VCR cassettes, no network
uv run python -m xkcd_search.indexer_main     # build a local index.sqlite (slow)
uv run fastmcp dev src/xkcd_search/server.py  # open the FastMCP inspector
```

The indexer caches to `platformdirs.user_cache_dir("xkcd-search", "matheus")`
by default; override with `XKCD_INDEX_DIR`.

For a fast CI iteration against the daily workflow, set `XKCD_INDEXER_LIMIT`
(or pass `limit` via `workflow_dispatch`) to cap how many new comics one run
fetches.

## Hosting

The server is designed to be dead simple to host: one Python process, one
downloaded SQLite file. There is no database, no secrets, no credentials.

**Current:** FastMCP Cloud, free tier. The free tier requires the server to
sit behind an OAuth provider (Horizon by Prefect) for anonymous public access,
which is a barrier for some MCP clients. The endpoint above works for clients
that support OAuth; for clients that don't, see the fallback.

**Fallback — Hugging Face Spaces (CPU Basic).** Free forever, 16 GB RAM, 2
vCPU, no credit card. Cold-starts after ~48 h idle but serves unauthenticated
HTTPS once warm. Migration is a Docker-SDK Space that runs FastMCP's HTTP
transport. No code change is required — the server downloads its own data on
first query regardless of where it runs.

## Contributing

Open work items live in [`TODO.md`](./TODO.md). The long-form architectural
plan is at `/home/matheus/.claude/plans/i-will-start-a-dapper-wreath.md`
(local to the original author).

## Attribution and licensing

Search results are indexed from explainxkcd.com, licensed under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). The generated
index inherits that license; see `DATA_LICENSE`. When citing a result, link
back to the comic's `url` and credit the explainxkcd contributors.

Comic images remain the work of Randall Munroe, licensed under
[CC BY-NC 2.5](https://xkcd.com/license.html). This project links to those
images but never rehosts them.

The source code in this repository is licensed under
[Apache 2.0](./LICENSE). See `NOTICE` for the full attribution stack.
