from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from internhunter.match.embed import (
    EmbeddingCache,
    cosine,
    cosine_matrix,
    embed_texts,
    normalize,
)


class FakeEncoder:
    def __init__(self, dim: int = 16) -> None:
        self.dim = dim
        self.calls = 0

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        self.calls += 1
        rows = []
        for text in texts:
            seed = int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            rows.append(rng.standard_normal(self.dim))
        return np.asarray(rows, dtype=np.float32)


def test_normalize_unit_vectors() -> None:
    vecs = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    out = normalize(vecs)
    assert abs(float(np.linalg.norm(out[0])) - 1.0) < 1e-6
    assert float(np.linalg.norm(out[1])) == 0.0


def test_cosine_identity_and_symmetry() -> None:
    enc = FakeEncoder()
    a = enc.encode(["software engineering intern"])
    assert abs(cosine(a, a) - 1.0) < 1e-5
    b = enc.encode(["marketing manager"])
    assert cosine(a, b) == cosine(b, a)


def test_cosine_matrix_shape() -> None:
    enc = FakeEncoder()
    q = enc.encode(["query"])
    m = enc.encode(["a", "b", "c"])
    sims = cosine_matrix(q, m)
    assert sims.shape == (1, 3)


def test_embed_cache_avoids_recompute(tmp_path: Path) -> None:
    enc = FakeEncoder()
    cache = EmbeddingCache(tmp_path, "fake")
    texts = ["one", "two"]
    first = embed_texts(texts, enc, cache)
    calls_after_first = enc.calls
    second = embed_texts(texts, enc, cache)
    assert enc.calls == calls_after_first
    assert np.allclose(first, second)


def test_corrupt_cache_file_is_treated_as_miss(tmp_path: Path) -> None:
    enc = FakeEncoder(dim=16)
    cache = EmbeddingCache(tmp_path, "fake")
    # Overwrite the cache file for "one" with non-.npy garbage.
    path = cache._path("one")
    path.write_bytes(b"not a valid npy file")
    out = embed_texts(["one"], enc, cache)
    assert out.shape == (1, 16)  # re-encoded, no crash


def test_wrong_dim_cache_file_is_treated_as_miss(tmp_path: Path) -> None:
    enc = FakeEncoder(dim=16)
    cache = EmbeddingCache(tmp_path, "fake")
    # Seed a good 16-dim vector for "one", then poison "two" with a wrong-dim (8) vector.
    embed_texts(["one"], enc, cache)
    cache.set("two", np.ones(8, dtype=np.float32))
    out = embed_texts(["one", "two"], enc, cache)
    assert out.shape == (2, 16)  # mismatched "two" re-encoded to 16-dim, vstack works
