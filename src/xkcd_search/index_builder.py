"""SQLite + sqlite-vec index construction and query."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import sqlite_vec

from xkcd_search import embeddings
from xkcd_search.config import EMBED_DIM
from xkcd_search.sources import ExplainArticle, XkcdMeta, chunk_comic

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def open_connection(path: Path, read_only: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec loaded and the schema initialised."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    if not read_only:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    return conn


def iter_known_comics(conn: sqlite3.Connection) -> dict[int, str | None]:
    """Return {comic_number: explained_at} for every row already in the index."""
    rows = conn.execute("SELECT number, explained_at FROM comics").fetchall()
    return {int(number): explained_at for number, explained_at in rows}


def _replace_chunks(
    conn: sqlite3.Connection,
    number: int,
    chunk_kinds: list[str],
    chunk_texts: list[str],
    vectors: np.ndarray,
) -> None:
    # sqlite-vec's vec0 virtual table doesn't support FK cascade, so delete both tables
    # by a subquery on the parent rowid set rather than N executemany round-trips.
    conn.execute(
        "DELETE FROM chunk_vec WHERE rowid IN (SELECT rowid FROM chunks WHERE number = ?)",
        (number,),
    )
    conn.execute("DELETE FROM chunks WHERE number = ?", (number,))
    for kind, text, vector in zip(chunk_kinds, chunk_texts, vectors, strict=True):
        cursor = conn.execute(
            "INSERT INTO chunks(number, kind, text) VALUES (?, ?, ?)",
            (number, kind, text),
        )
        rowid = cursor.lastrowid
        conn.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
            (rowid, vector.tobytes()),
        )


def upsert_comic(
    conn: sqlite3.Connection,
    xkcd: XkcdMeta,
    article: ExplainArticle | None,
) -> None:
    """Insert or replace the comic row and rebuild its chunk + vector rows."""
    chunks = chunk_comic(xkcd, article)
    kinds = [c.kind for c in chunks]
    texts = [c.text for c in chunks]
    vectors = embeddings.encode(texts) if texts else np.zeros((0, EMBED_DIM), dtype=np.float32)

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
            article.wikitext if article is not None else None,
            explained_at,
        ),
    )
    _replace_chunks(conn, xkcd.number, kinds, texts, vectors)
    conn.commit()


def query_top_k(
    conn: sqlite3.Connection,
    query_vec: np.ndarray,
    k: int,
) -> list[tuple[int, float]]:
    """Return [(comic_number, similarity)] dedup'd by comic, highest similarity first."""
    assert query_vec.dtype == np.float32
    assert query_vec.shape == (EMBED_DIM,)
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
        n = int(number)
        d = float(distance)
        if n not in best or d < best[n]:
            best[n] = d
    ranked = sorted(best.items(), key=lambda item: item[1])[:k]
    return [(number, 1.0 - distance) for number, distance in ranked]
