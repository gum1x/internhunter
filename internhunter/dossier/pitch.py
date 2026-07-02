"""Load pitch.yaml — the user's outreach identity (positioning, proof points, and
per-tag "why I fit" angle lines). Consumed by dossier synthesis and outreach drafts."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Pitch:
    name: str = "I"
    positioning: str = ""
    proof_points: tuple[str, ...] = ()
    angles: dict[str, str] = field(default_factory=dict)

    def angle_for(self, tags: tuple[str, ...] | list[str], company: str) -> str:
        for tag in tags:
            line = self.angles.get(tag)
            if line:
                return line.strip().format(company=company)
        default = self.angles.get("default", "")
        return default.strip().format(company=company) if default else ""


def load_pitch(path: Path | str) -> Pitch:
    p = Path(path)
    if not p.exists():
        return Pitch()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return Pitch()
    angles = data.get("angles") or {}
    return Pitch(
        name=str(data.get("name") or "I"),
        positioning=str(data.get("positioning") or "").strip(),
        proof_points=tuple(str(p) for p in data.get("proof_points") or []),
        angles={str(k): str(v) for k, v in angles.items()} if isinstance(angles, dict) else {},
    )


@lru_cache(maxsize=4)
def _cached_pitch(path: str, mtime: float) -> Pitch:
    return load_pitch(path)


def get_pitch(path: Path | str) -> Pitch:
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _cached_pitch(str(p), mtime)
