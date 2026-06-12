from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from internhunter.config.settings import Settings
from internhunter.llm.client import (
    ApiBackend,
    CliBackend,
    LlmCache,
    cache_key,
    complete,
    extract_json,
    get_backend,
)


class FakeBackend:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        self.calls += 1
        return self.reply


def test_extract_json_from_noisy_text() -> None:
    text = 'Sure! Here is the result:\n{"fit": 87, "matched": ["python"]}\nHope that helps.'
    data = extract_json(text)
    assert data["fit"] == 87
    assert data["matched"] == ["python"]


def test_extract_json_raises_without_object() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here")


def _run_cli(monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str) -> CliBackend:
    class _Proc:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(*args: Any, **kwargs: Any) -> _Proc:
        return _Proc()

    monkeypatch.setattr("internhunter.llm.client.subprocess.run", fake_run)
    return CliBackend()


def test_cli_backend_non_json_stdout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _run_cli(monkeypatch, 0, "warning: deprecated\nnot json at all")
    with pytest.raises(RuntimeError):
        backend.generate("hi")


def test_cli_backend_missing_result_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _run_cli(monkeypatch, 0, '{"is_error": true, "fit": 0}')
    with pytest.raises(RuntimeError):
        backend.generate("hi")


def test_cli_backend_returns_result_string(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _run_cli(monkeypatch, 0, '{"result": "{\\"fit\\": 50}"}')
    assert backend.generate("hi") == '{"fit": 50}'


def test_complete_uses_cache(tmp_path: Path) -> None:
    backend = FakeBackend('{"x": 1}')
    cache = LlmCache(tmp_path)
    first = complete("prompt", backend, cache=cache, model="m")
    second = complete("prompt", backend, cache=cache, model="m")
    assert first == second == '{"x": 1}'
    assert backend.calls == 1


def test_cache_key_changes_with_inputs() -> None:
    a = cache_key("m", "p", None)
    b = cache_key("m", "p", "sys")
    c = cache_key("m2", "p", None)
    assert len({a, b, c}) == 3


def test_get_backend_selects_cli_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = get_backend(Settings(llm_backend="auto"))
    assert isinstance(backend, CliBackend)


def test_get_backend_cli_when_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    backend = get_backend(Settings(llm_backend="cli"))
    assert isinstance(backend, CliBackend)


def test_api_backend_requires_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError):
        ApiBackend("claude-opus-4-8")
