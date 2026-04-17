# xkcd-search-mcp

![status](https://img.shields.io/badge/status-WIP-yellow)

Semantic search for xkcd comics, served over the Model Context Protocol. Given a
natural-language prompt, the `search_xkcd` tool returns the top-K most relevant
comics from the full xkcd archive, indexed daily against the explainxkcd.com
wiki.

## Connect

Once deployed, the MCP endpoint will be available at:

```
https://<your-project>.fastmcp.app/mcp
```

Point any MCP client (Claude Desktop, mcp-inspector, Cursor, etc.) at that URL.

## The tool

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

Every result includes `number`, `title`, `url`, and `similarity`. The boolean
flags let the caller opt into heavier fields per call rather than baking the
choice into the server.

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
