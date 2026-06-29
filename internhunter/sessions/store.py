from __future__ import annotations

import json
from pathlib import Path

from internhunter.config.settings import Settings, get_settings


def session_path(settings: Settings, name: str) -> Path:
    base = settings.sessions_dir
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{name}.json"


def load_storage_state(settings: Settings, name: str) -> Path | None:
    path = session_path(settings, name)
    return path if path.exists() else None


def save_storage_state(settings: Settings, name: str, state: dict) -> Path:
    path = session_path(settings, name)
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def resolve_handshake_session(settings: Settings) -> Path | None:
    if settings.handshake_session.exists():
        return settings.handshake_session
    stored = load_storage_state(settings, "handshake")
    if stored is not None:
        return stored
    return None