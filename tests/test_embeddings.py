from __future__ import annotations

import numpy as np

from xkcd_search.config import EMBED_DIM
from xkcd_search.embeddings import encode


def test_encode_returns_normalized_float32_of_expected_shape():
    texts = ["hello world", "semantic search"]
    vectors = encode(texts)
    assert vectors.shape == (2, EMBED_DIM)
    assert vectors.dtype == np.float32
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_similar_sentences_are_closer_than_dissimilar_ones():
    vectors = encode(
        [
            "A cartoonist draws webcomics about science and romance.",
            "Webcomic artist writes comics about physics and love.",
            "The central bank raised interest rates to fight inflation.",
        ]
    )
    sim_close = float(np.dot(vectors[0], vectors[1]))
    sim_far = float(np.dot(vectors[0], vectors[2]))
    assert sim_close > 0.6
    assert sim_far < 0.5
    assert sim_close > sim_far
