from __future__ import annotations

import pathlib
from typing import Any

from internhunter.core.models import NormalizedJob
from internhunter.match.embed import (
    EmbeddingCache,
    Encoder,
    cosine_matrix,
    embed_texts,
)

_PROFILE_KEYS = ("name", "skills", "interests", "target_sectors", "seeking")


def _default_profile_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "config" / "profile.yaml"


def _flatten(value: Any) -> list[str]:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten(item))
        return parts
    if value is None:
        return []
    return [str(value).strip()]


def _parse_minimal(text: str) -> dict[str, Any]:
    data: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if current is not None:
                data.setdefault(current, []).append(line.split("- ", 1)[1].strip())
            continue
        if ":" in line and not line.startswith(" "):
            key, _, rest = line.partition(":")
            current = key.strip()
            scalar = rest.strip()
            if scalar:
                data[current] = [scalar]
            else:
                data.setdefault(current, [])
    return dict(data)


def load_profile_text(path: pathlib.Path | None = None) -> str:
    target = path or _default_profile_path()
    raw = target.read_text(encoding="utf-8")
    data: dict[str, Any]
    try:
        import yaml

        loaded = yaml.safe_load(raw)
        data = loaded if isinstance(loaded, dict) else {}
    except ImportError:
        data = _parse_minimal(raw)
    parts: list[str] = []
    for key in _PROFILE_KEYS:
        parts.extend(_flatten(data.get(key)))
    return ". ".join(part for part in parts if part)


def job_text(job: NormalizedJob) -> str:
    return f"{job.title}. {job.description_text}".strip()


def rank_jobs(
    profile_text: str,
    jobs: list[NormalizedJob],
    encoder: Encoder,
    cache: EmbeddingCache | None = None,
) -> list[tuple[NormalizedJob, float]]:
    if not jobs:
        return []
    texts = [profile_text, *(job_text(job) for job in jobs)]
    matrix = embed_texts(texts, encoder, cache)
    scores = cosine_matrix(matrix[0], matrix[1:])[0]
    ranked = [
        (job, max(0.0, min(1.0, float(score))))
        for job, score in zip(jobs, scores, strict=True)
    ]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked
