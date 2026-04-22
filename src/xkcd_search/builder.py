"""Rebuild the local SQLite index from xkcd.com and explainxkcd.com.

Run `python -m xkcd_search.builder`. The nightly GitHub Actions job invokes this
module; the server imports only `encode`, `open_connection`, and `query_top_k`
at runtime.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx
import mwparserfromhell
import numpy as np
import sqlite_vec
from sentence_transformers import SentenceTransformer

INDEX_PATH = Path.home() / ".cache" / "xkcd-search" / "index.sqlite"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384

USER_AGENT = "xkcd-search-mcp (https://github.com/matheusccouto/xkcd-search-mcp)"
XKCD_BASE = "https://xkcd.com"
EXPLAIN_API = "https://www.explainxkcd.com/wiki/api.php"

MIN_CHUNK_CHARS = 20
MAX_CHUNK_WORDS = 380  # ~500 tokens at 1.3 tokens/word
SKIP_NUMBERS = {404}


@dataclass(frozen=True)
class XkcdMeta:
    number: int
    title: str
    transcript: str
    img: str
    alt: str
    url: str


@dataclass(frozen=True)
class ExplainArticle:
    number: int
    wikitext: str


@dataclass(frozen=True)
class Chunk:
    kind: str
    text: str


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL_NAME)


def encode(texts: list[str]) -> np.ndarray:
    """L2-normalized float32 vectors, shape (len(texts), EMBED_DIM).

    Normalization at write time reduces cosine similarity to a dot product, which
    sqlite-vec handles natively on the vec0 virtual table.
    """
    vectors = _model().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vectors.astype(np.float32, copy=False)


def new_client(timeout: float = 30.0, follow_redirects: bool = False) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=follow_redirects
    )


def fetch_latest_xkcd_number(client: httpx.Client) -> int:
    data = client.get(f"{XKCD_BASE}/info.0.json").raise_for_status().json()
    return int(data["num"])


def fetch_xkcd(number: int, client: httpx.Client) -> XkcdMeta:
    data = client.get(f"{XKCD_BASE}/{number}/info.0.json").raise_for_status().json()
    return XkcdMeta(
        number=int(data["num"]),
        title=str(data.get("title", "")),
        transcript=str(data.get("transcript", "")),
        img=str(data.get("img", "")),
        alt=str(data.get("alt", "")),
        url=f"{XKCD_BASE}/{number}/",
    )


def fetch_explainxkcd(number: int, client: httpx.Client) -> ExplainArticle | None:
    """Fetch the explainxkcd wikitext for a comic. Returns None when absent."""
    resp = client.get(
        EXPLAIN_API,
        params={
            "action": "parse",
            "page": str(number),
            "redirects": "1",
            "prop": "wikitext",
            "format": "json",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        return None
    wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
    return ExplainArticle(number=number, wikitext=wikitext) if wikitext else None


def _split_long(kind: str, body: str) -> list[Chunk]:
    paragraphs = [p.strip() for p in body.split("\n\n") if len(p.strip()) >= MIN_CHUNK_CHARS]
    chunks: list[Chunk] = []
    buffer = ""
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if buffer and len(candidate.split()) > MAX_CHUNK_WORDS:
            chunks.append(Chunk(kind=kind, text=buffer))
            buffer = para
        else:
            buffer = candidate
    if buffer.strip():
        chunks.append(Chunk(kind=kind, text=buffer))
    return chunks


def chunk_comic(xkcd: XkcdMeta, article: ExplainArticle | None) -> list[Chunk]:
    """Always emits a title chunk, plus transcript and one chunk per explainxkcd section."""
    chunks: list[Chunk] = [Chunk(kind="title", text=xkcd.title)]
    if xkcd.transcript.strip():
        chunks.append(Chunk(kind="transcript", text=xkcd.transcript.strip()))
    if article is None:
        return chunks

    for section in mwparserfromhell.parse(article.wikitext).get_sections(
        flat=True, include_lead=True, include_headings=True
    ):
        headings = section.filter_headings()
        heading = str(headings[0].title).strip().lower() if headings else "lead"
        kind = f"section:{heading}"
        body = str(section.strip_code()).strip()
        if len(body) < MIN_CHUNK_CHARS:
            continue
        if len(body.split()) > MAX_CHUNK_WORDS:
            chunks.extend(_split_long(kind, body))
        else:
            chunks.append(Chunk(kind=kind, text=body))
    return chunks


def open_connection(path: Path, read_only: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec loaded and the schema initialised."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    if not read_only:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    return conn


def get_indexed_comics(conn: sqlite3.Connection) -> dict[int, str | None]:
    """Return comic numbers mapped to their `explained_at` timestamp (or None).

    Comics with a non-None value have been indexed with explainxkcd content and
    are skipped during incremental rebuilds. Comics with None are re-indexed to
    catch newly-added explanations.
    """
    rows = conn.execute("SELECT number, explained_at FROM comics").fetchall()
    return {int(number): explained_at for number, explained_at in rows}


def upsert_comic(conn: sqlite3.Connection, xkcd: XkcdMeta, article: ExplainArticle | None) -> None:
    """Insert or replace the comic row and rebuild its chunk + vector rows."""
    chunks = chunk_comic(xkcd, article)
    texts = [c.text for c in chunks]
    vectors = encode(texts) if texts else np.zeros((0, EMBED_DIM), dtype=np.float32)
    explained_at = datetime.now(UTC).isoformat() if article is not None else None

    conn.execute(
        """
        INSERT INTO comics(number, title, url, image_url, alt_text, transcript,
                           explanation, explained_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(number) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            image_url = excluded.image_url,
            alt_text = excluded.alt_text,
            transcript = excluded.transcript,
            explanation = excluded.explanation,
            explained_at = excluded.explained_at
        """,
        (
            xkcd.number,
            xkcd.title,
            xkcd.url,
            xkcd.img,
            xkcd.alt,
            xkcd.transcript,
            article.wikitext if article else None,
            explained_at,
        ),
    )
    conn.execute(
        "DELETE FROM chunk_vec WHERE rowid IN (SELECT rowid FROM chunks WHERE number = ?)",
        (xkcd.number,),
    )
    conn.execute("DELETE FROM chunks WHERE number = ?", (xkcd.number,))
    for chunk, vector in zip(chunks, vectors, strict=True):
        cursor = conn.execute(
            "INSERT INTO chunks(number, kind, text) VALUES (?, ?, ?)",
            (xkcd.number, chunk.kind, chunk.text),
        )
        conn.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
            (cursor.lastrowid, vector.tobytes()),
        )
    conn.commit()


def query_top_k(conn: sqlite3.Connection, query_vec: np.ndarray, k: int) -> list[int]:
    """Return comic numbers ranked by similarity to `query_vec`, dedup'd by comic."""
    pool = max(k * 10, 50)
    rows = conn.execute(
        """
        SELECT chunks.number, chunk_vec.distance
        FROM chunk_vec
        JOIN chunks USING(rowid)
        WHERE chunk_vec.embedding MATCH ? AND k = ?
        ORDER BY chunk_vec.distance
        """,
        (query_vec.tobytes(), pool),
    ).fetchall()
    best: dict[int, float] = {}
    for number, distance in rows:
        n, d = int(number), float(distance)
        if n not in best or d < best[n]:
            best[n] = d
    return [n for n, _ in sorted(best.items(), key=lambda item: item[1])[:k]]


def main() -> int:
    conn = open_connection(INDEX_PATH)
    with new_client() as client:
        latest = fetch_latest_xkcd_number(client)
        indexed = get_indexed_comics(conn)
        print(f"latest comic: {latest}; already indexed: {len(indexed)}", flush=True)

        processed = 0
        for n in range(1, latest + 1):
            if n in SKIP_NUMBERS or indexed.get(n) is not None:
                continue
            xkcd = fetch_xkcd(n, client)
            article = fetch_explainxkcd(n, client)
            upsert_comic(conn, xkcd, article)
            processed += 1
            if processed % 50 == 0:
                print(f"processed {processed} comics (current: {n})", flush=True)

    total = conn.execute("SELECT COUNT(*) FROM comics").fetchone()[0]
    with_article = conn.execute(
        "SELECT COUNT(*) FROM comics WHERE explained_at IS NOT NULL"
    ).fetchone()[0]
    print(f"done: {total} comics, {with_article} with article", flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
