---
title: xkcd-search
emoji: 🔎
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# xkcd-search-mcp

Semantic search for xkcd comics, served over the Model Context Protocol. Given a
natural-language prompt, the `search_xkcd` tool returns the top-K most relevant
comics from the full xkcd archive, indexed daily against the explainxkcd.com
wiki.

## Connect

The public MCP endpoint:

```
https://couto-xkcd-search.hf.space/mcp
```

Point any MCP client (Claude Desktop, mcp-inspector, Cursor, etc.) at that URL.
It is anonymous HTTPS; no OAuth or API key is required.

## The tool

```python
search_xkcd(query: str, k: int = 5) -> list[dict]
```

Semantic top-K lookup. Every result is a dict with `number`, `title`, `url`,
`image_url`, `alt_text`, `transcript`, and `explanation`. Cite `url` when
referencing a comic.

## How it works

1. A daily GitHub Actions job (`.github/workflows/index-daily.yml`) fetches
   every xkcd comic's JSON and, when available, its explainxkcd wikitext.
2. Each comic is split into a title chunk, a transcript chunk, and one chunk
   per explainxkcd `== Section ==`. Long sections are split on paragraph breaks.
3. Chunks are embedded with `BAAI/bge-small-en-v1.5` (384-dim, L2-normalized)
   and written into a single `index.sqlite` file backed by `sqlite-vec`.
4. The artifact is published as the `index.sqlite` asset on the repo's latest
   GitHub Release, and the workflow calls the Hugging Face Spaces restart API
   to trigger a rebuild.
5. The FastMCP server downloads that asset on boot. Queries run locally
   against the SQLite file; there is no background polling.

There is no hosted database and no API key anywhere in the stack.

## Local development

```bash
uv sync
uv run pytest                                   # integration tests (in-process)
uv run python -m xkcd_search.builder            # build a local index.sqlite (slow)
uv run fastmcp dev src/xkcd_search/server.py    # open the FastMCP inspector
```

The builder writes to `~/.cache/xkcd-search/index.sqlite`. Delete that file
to force a re-download on the next server boot.

## Testing

```bash
uv run pytest                                             # in-process integration
XKCD_TEST_URL=https://couto-xkcd-search.hf.space/mcp \
    uv run pytest tests/test_server.py                    # hit the live Space
```

Tests use an in-process `fastmcp.Client` against a 3-comic fixture index
built once per session by fetching real data from xkcd.com and
explainxkcd.com. Setting `XKCD_TEST_URL` redirects the suite at a deployed
endpoint instead.

## Hosting

The server is designed to be dead simple to host: one Python process, one
downloaded SQLite file. There is no database, no secrets, no credentials.

Runs on Hugging Face Spaces (CPU Basic, free tier: 16 GB RAM, 2 vCPU) as a
Docker-SDK Space. The `Dockerfile` at the repo root is the build recipe. The
Space is linked to this GitHub repo, so every push to `main` triggers a rebuild.
Spaces on the free tier cold-start after ~48 h idle; first request after a long
sleep pays the wake-up latency.

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
