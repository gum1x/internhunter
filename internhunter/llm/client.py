from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Protocol

from internhunter.config.settings import Settings, get_settings

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class LlmBackend(Protocol):
    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str: ...


class CliBackend:
    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        full = f"{system}\n\n{prompt}" if system else prompt
        proc = subprocess.run(
            ["claude", "-p", full, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude cli failed: {proc.stderr.strip()[:200]}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"claude cli returned non-json stdout: {proc.stdout[:200]!r}"
            ) from exc
        result = envelope.get("result") if isinstance(envelope, dict) else None
        if not isinstance(result, str):
            raise RuntimeError(f"claude cli returned unexpected envelope: {proc.stdout[:200]!r}")
        return result


class ApiBackend:
    def __init__(self, model: str) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic()

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def get_backend(settings: Settings | None = None) -> LlmBackend:
    resolved = settings or get_settings()
    choice = resolved.llm_backend
    if choice == "api" or (choice == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return ApiBackend(resolved.llm_model)
    return CliBackend()


class LlmCache:
    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir / "llm"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> str | None:
        path = self._path(key)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def set(self, key: str, value: str) -> None:
        self._path(key).write_text(value, encoding="utf-8")


def cache_key(model: str, prompt: str, system: str | None) -> str:
    raw = " ".join([model, system or "", prompt])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_json(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text)
    if match is None:
        raise ValueError("no json object found in llm response")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("llm response json is not an object")
    return parsed


def complete(
    prompt: str,
    backend: LlmBackend,
    system: str | None = None,
    max_tokens: int = 1024,
    cache: LlmCache | None = None,
    model: str = "cli",
) -> str:
    if cache is not None:
        key = cache_key(model, prompt, system)
        hit = cache.get(key)
        if hit is not None:
            return hit
    result = backend.generate(prompt, system=system, max_tokens=max_tokens)
    if cache is not None:
        cache.set(cache_key(model, prompt, system), result)
    return result
