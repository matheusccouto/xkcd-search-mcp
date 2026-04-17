"""Fetchers for xkcd.com JSON and explainxkcd.com MediaWiki, plus the chunker."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import mwparserfromhell

from xkcd_search.config import USER_AGENT

XKCD_BASE = "https://xkcd.com"
EXPLAIN_API = "https://www.explainxkcd.com/wiki/api.php"

MIN_CHUNK_CHARS = 20
MAX_CHUNK_WORDS = 380  # ~500 tokens at 1.3 tokens/word


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


def new_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0)


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
    """Fetch the explainxkcd wikitext for a comic. Returns None when the page is absent."""
    params = {
        "action": "parse",
        "page": str(number),
        "redirects": "1",
        "prop": "wikitext",
        "format": "json",
    }
    resp = client.get(EXPLAIN_API, params=params)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        return None
    wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
    if not wikitext:
        return None
    return ExplainArticle(number=number, wikitext=wikitext)


def _word_count(text: str) -> int:
    return len(text.split())


def _split_long_section(kind: str, body: str) -> list[Chunk]:
    """Split a section into paragraph-group chunks when it exceeds MAX_CHUNK_WORDS."""
    paragraphs = [p.strip() for p in body.split("\n\n") if len(p.strip()) >= MIN_CHUNK_CHARS]
    chunks: list[Chunk] = []
    buffer = ""
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if buffer and _word_count(candidate) > MAX_CHUNK_WORDS:
            chunks.append(Chunk(kind=kind, text=buffer))
            buffer = para
        else:
            buffer = candidate
    if buffer.strip():
        chunks.append(Chunk(kind=kind, text=buffer))
    return chunks


def _section_kind(heading_text: str | None) -> str:
    if heading_text is None:
        return "section:lead"
    slug = heading_text.strip().lower()
    return f"section:{slug}"


def chunk_comic(xkcd: XkcdMeta, article: ExplainArticle | None) -> list[Chunk]:
    """Turn a comic and its explainxkcd article into embedding-ready chunks.

    Always emits a title chunk, plus a transcript chunk when the xkcd JSON carries one.
    If an article is present, one chunk per ``== Section ==`` is added; long sections
    are split on paragraph breaks.
    """
    chunks: list[Chunk] = [Chunk(kind="title", text=xkcd.title)]
    if xkcd.transcript.strip():
        chunks.append(Chunk(kind="transcript", text=xkcd.transcript.strip()))
    if article is None:
        return chunks

    parsed = mwparserfromhell.parse(article.wikitext)
    sections = parsed.get_sections(flat=True, include_lead=True, include_headings=True)
    for section in sections:
        headings = section.filter_headings()
        heading_text = str(headings[0].title).strip() if headings else None
        kind = _section_kind(heading_text)
        body = str(section.strip_code()).strip()
        if len(body) < MIN_CHUNK_CHARS:
            continue
        if _word_count(body) > MAX_CHUNK_WORDS:
            chunks.extend(_split_long_section(kind, body))
        else:
            chunks.append(Chunk(kind=kind, text=body))
    return chunks
