from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from internhunter.config.settings import get_settings


class Encoder(Protocol):
    def encode(self, texts: list[str]) -> NDArray[np.float32]: ...


class SentenceTransformerEncoder:
    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        self._model = SentenceTransformer(
            model_name or settings.embed_model, device=settings.embed_device
        )

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)


def default_encoder(model_name: str | None = None) -> Encoder:
    return SentenceTransformerEncoder(model_name)


def normalize(vectors: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


def cosine_matrix(
    query: NDArray[np.float32], matrix: NDArray[np.float32]
) -> NDArray[np.float32]:
    if query.ndim == 1:
        query = query.reshape(1, -1)
    return (normalize(query) @ normalize(matrix).T).astype(np.float32)


def cosine(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
    return float(cosine_matrix(a, b)[0, 0])


def _text_key(model_name: str, text: str) -> str:
    digest = hashlib.sha1(f"{model_name}::{text}".encode()).hexdigest()
    return digest


class EmbeddingCache:
    def __init__(self, cache_dir: Path, model_name: str) -> None:
        self.dir = cache_dir / "embeddings"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name

    def _path(self, text: str) -> Path:
        return self.dir / f"{_text_key(self.model_name, text)}.npy"

    def get(self, text: str) -> NDArray[np.float32] | None:
        path = self._path(text)
        if not path.exists():
            return None
        try:
            loaded: NDArray[np.float32] = np.load(path).astype(np.float32)
        except (ValueError, OSError, EOFError):
            # Corrupt / partially-written file: treat as a cache miss, re-encode.
            return None
        if loaded.ndim != 1 or loaded.size == 0:
            return None
        return loaded

    def set(self, text: str, vector: NDArray[np.float32]) -> None:
        # Write to a temp file then atomically rename, so an interrupted write can
        # never leave a half-written (permanently corrupt) .npy behind.
        path = self._path(text)
        # Keep the .npy suffix so np.save doesn't append another one.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp.npy")
        np.save(tmp, vector.astype(np.float32))
        os.replace(tmp, path)


def embed_texts(
    texts: list[str],
    encoder: Encoder,
    cache: EmbeddingCache | None = None,
) -> NDArray[np.float32]:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    if cache is None:
        return normalize(encoder.encode(texts))

    vectors: list[NDArray[np.float32] | None] = [cache.get(text) for text in texts]

    def _encode_into(slots: list[int]) -> None:
        if not slots:
            return
        fresh = normalize(encoder.encode([texts[i] for i in slots]))
        for slot, vec in zip(slots, fresh, strict=True):
            cache.set(texts[slot], vec)
            vectors[slot] = vec

    missing = [i for i, vec in enumerate(vectors) if vec is None]
    _encode_into(missing)

    # A cached vector whose dim disagrees with the others (e.g. a same-key corrupt
    # file or a stale model output) would crash vstack. Re-encode such outliers
    # instead of killing the run.
    dims = [vec.shape[-1] for vec in vectors if vec is not None]
    if dims:
        expected_dim = max(set(dims), key=dims.count)  # modal dim
        wrong_dim = [
            i
            for i, vec in enumerate(vectors)
            if vec is not None and vec.shape[-1] != expected_dim
        ]
        _encode_into(wrong_dim)
    return np.vstack([vec for vec in vectors if vec is not None]).astype(np.float32)
