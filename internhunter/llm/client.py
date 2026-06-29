from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Protocol

from internhunter.config.settings import Settings, get_settings

# Transient failures worth a bounded retry (network/timeout). Deterministic content
# errors (bad JSON, unexpected envelope) are NOT here — they should fail fast.
_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
    subprocess.TimeoutExpired,
)


class LlmBackend(Protocol):
    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str: ...


class CliBackend:
    def __init__(
        self, timeout: float = 120.0, claude_bin: str = "claude", model: str | None = None
    ) -> None:
        self.timeout = timeout
        self.claude_bin = claude_bin
        self.model = model

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        full = f"{system}\n\n{prompt}" if system else prompt
        args = [self.claude_bin, "-p", full, "--output-format", "json"]
        if self.model:
            args += ["--model", self.model]
        proc = subprocess.run(
            args,
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
    def __init__(self, model: str, timeout: float = 120.0, max_retries: int = 2) -> None:
        import anthropic

        self.model = model
        self.timeout = timeout
        # Let the SDK retry transient errors (429/5xx/timeouts) with backoff.
        self._client = anthropic.Anthropic(max_retries=max_retries)

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            timeout=self.timeout,
        )
        return "".join(block.text for block in response.content if block.type == "text")


class LocalBackend:
    """OpenAI-compatible chat endpoint (e.g. a llama.cpp server)."""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": self.model, "messages": messages, "max_tokens": max_tokens},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            # An error body (or empty completion) has no choices; surface a clear error
            # so callers skip this job instead of seeing an opaque KeyError/IndexError.
            raise RuntimeError(f"local backend returned no choices: {str(data)[:200]!r}")
        return str(choices[0]["message"]["content"])


def get_backend(settings: Settings | None = None) -> LlmBackend:
    resolved = settings or get_settings()
    choice = resolved.llm_backend
    if choice == "local" or (choice == "auto" and resolved.llm_base_url):
        if resolved.llm_base_url:
            return LocalBackend(resolved.llm_base_url, resolved.llm_model)
    if choice == "api" or (choice == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return ApiBackend(resolved.llm_model)
    return CliBackend(claude_bin=resolved.claude_bin, model=resolved.llm_model)


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


def _balanced_objects(text: str) -> list[str]:
    """Yield every balanced top-level {...} span, in order of appearance.

    A greedy first-{ to last-} match breaks when prose before the JSON contains
    its own braces (e.g. "use {} here"). Brace-counting (string/escape aware)
    isolates each real object instead.
    """
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    spans.append(text[start : i + 1])
                    start = -1
    return spans


def extract_json(text: str) -> dict[str, Any]:
    # Prefer the LAST balanced object: models tend to emit reasoning/prose (which may
    # itself contain braces) before the final answer JSON.
    for span in reversed(_balanced_objects(text)):
        try:
            parsed = json.loads(span)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no json object found in llm response")


def complete(
    prompt: str,
    backend: LlmBackend,
    system: str | None = None,
    max_tokens: int = 1024,
    cache: LlmCache | None = None,
    model: str = "cli",
    max_attempts: int = 2,
) -> str:
    if cache is not None:
        key = cache_key(model, prompt, system)
        hit = cache.get(key)
        if hit is not None:
            return hit
    # Small bounded retry for TRANSIENT backend failures only (timeouts / dropped
    # connections). Content/parse errors (e.g. non-json stdout) are deterministic, so
    # we let them propagate immediately for the caller to skip the job.
    last_exc: Exception | None = None
    for _ in range(max(1, max_attempts)):
        try:
            result = backend.generate(prompt, system=system, max_tokens=max_tokens)
            break
        except _TRANSIENT_ERRORS as exc:
            last_exc = exc
    else:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM generation failed without a transient error")
    if cache is not None:
        cache.set(cache_key(model, prompt, system), result)
    return result
