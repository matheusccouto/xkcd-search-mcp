"""Sentence embedding wrapper with lazy model loading."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from xkcd_search.config import EMBED_DIM, EMBED_MODEL_NAME


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL_NAME)


def encode(texts: list[str]) -> np.ndarray:
    """Encode texts into L2-normalized float32 vectors of shape (len(texts), EMBED_DIM).

    Normalized output means cosine similarity reduces to a dot product, which sqlite-vec
    handles natively via its distance metric on the vec0 virtual table.
    """
    vectors = _model().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    vectors = vectors.astype(np.float32, copy=False)
    assert vectors.shape == (len(texts), EMBED_DIM), f"unexpected embedding shape {vectors.shape}"
    return vectors
