# xkcd-search-mcp

Remote MCP server exposing a single tool, `search_xkcd`, for semantic search over xkcd plus explainxkcd. The corpus is rebuilt nightly by a GitHub Action, shipped as an `index.sqlite` Release asset, and the workflow pushes an empty commit to `main` so FastMCP cloud auto-redeploys. The server downloads the asset once at boot; there is no polling. The live endpoint is `https://xkcd-search.fastmcp.app/mcp`.

## Layout

- `src/xkcd_search/server.py` FastMCP server, `search_xkcd` tool, boot-time download
- `src/xkcd_search/builder.py` HTTP fetchers, chunker, embeddings, SQLite upsert, nightly `__main__`
- `src/xkcd_search/schema.sql` sqlite-vec schema
- `tests/` pytest-asyncio integration tests (in-process or cloud via `XKCD_TEST_URL`)
- `.github/workflows/index-daily.yml` daily build, publish, redeploy

## Tech stack

Python 3.12, managed with `uv`. Linting `ruff`, typechecking `ty`. MCP via `fastmcp`. Embeddings via `sentence-transformers`. Vector search via `sqlite-vec`.

## Commands

- `uv sync` install
- `uv run pytest` integration tests (in-process Client, hits xkcd.com + explainxkcd.com once per session to build the fixture)
- `XKCD_TEST_URL=https://xkcd-search.fastmcp.app/mcp uv run pytest tests/test_server.py` run the same suite against the live cloud endpoint (OAuth, opt-in)
- `uv run ruff check . && uv run ruff format --check . && uv run ty check` lint plus typecheck
- `uv run python -m xkcd_search.builder` rebuild the index locally (full run, no limit flag)
- `uv run fastmcp dev src/xkcd_search/server.py` open the FastMCP inspector

<important if="you are writing or modifying tests">
- pytest-asyncio runs in auto mode. Write `async def test_...`; do NOT wrap in `asyncio.run(...)`.
- Server tests use the `mcp_client` fixture in `tests/conftest.py`. It picks in-process `Client(server.mcp)` by default and `Client(XKCD_TEST_URL, auth="oauth")` when that env var is set.
- The `built_index` fixture (session-scoped) fetches 3 real comics from xkcd.com + explainxkcd.com, builds a SQLite index in a temp dir, and swaps `server._conn`. It is a no-op in cloud mode because cloud tests hit the real production index.
- No VCR, no cassettes, no mocks. If xkcd.com or explainxkcd.com is unreachable, `built_index` fails loudly. That is intentional: the tests are integration tests by design.
- If something is hard to test without a mock, the code under test has a design problem; fix that first.
</important>

<important if="you are editing src/xkcd_search/server.py or adding MCP tools">
- Tool args are the public contract: every arg shows up in the schema the LLM sees. Use explicit bool flags, not `fields: list[str]`.
- Every returned comic must include `number`, `title`, `url`. The `url` is what the LLM cites; removing it breaks attribution under CC BY-SA 3.0.
- Boot-time download + open read-only conn runs at import time unless `XKCD_SKIP_BOOTSTRAP=1` or pytest is detected (`"pytest" in sys.modules`). Do not bypass the pytest check; it is how tests avoid touching GitHub Releases.
- There is no poll thread and no lock. `_conn` is set once at import. Tests monkeypatch it; runtime never mutates it. Do not reintroduce background swapping without a reason stronger than "updates feel slow" — the redeploy-on-release flow replaces what the poll thread used to do.
- The server always downloads if `INDEX_PATH` does not exist. For local dev with a stale index, delete the file to force a refresh.
</important>

<important if="you are modifying the SQLite schema or sqlite-vec usage">
- `chunk_vec` uses `distance_metric=cosine`. `query_top_k` orders by raw distance and returns bare comic numbers; the server no longer exposes a `similarity` score. Changing the metric silently breaks ranking.
- Embeddings are L2-normalized at write time in `builder.encode` (`normalize_embeddings=True`). Do not re-normalize at query time.
- Schema lives in `src/xkcd_search/schema.sql` and is applied on every `open_connection(..., read_only=False)`. Changing it invalidates every published release artifact until the next rebuild.
</important>

<important if="you are editing .github/workflows/index-daily.yml">
- The `schedule: 0 5 * * *` plus `workflow_dispatch` combination is the only thing keeping the scheduled workflow from auto-disabling after 60 days of inactivity on a dormant repo.
- The Hugging Face model cache key is `hf-hub-bge-small-en-v1.5`. If the embedding model changes, bump the key or cached weights will go stale.
- `concurrency: group: index-daily, cancel-in-progress: false`, keep this. Two overlapping indexers corrupt the release asset.
- The final step pushes an empty commit to `main`. FastMCP cloud redeploys on push and the new process downloads the fresh Release asset on boot. If you swap this for a webhook, make sure the redeploy actually happens; otherwise the server will keep serving yesterday's data.
- The actions/cache entry at `~/.cache/xkcd-search` is the partial-build cache. The builder is incremental: each run starts from yesterday's SQLite and only fetches new comics. Losing the cache forces a full rebuild (~1 hour).
</important>

## Licenses

Code: Apache 2.0. Data (embeddings plus stored explainxkcd text): CC BY-SA 3.0. Attribution is delivered via the `url` field in every search result.
