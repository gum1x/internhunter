from __future__ import annotations

import builtins
from typing import Any

import pytest

from internhunter.config.settings import Settings
from internhunter.core.browser import BrowserFactory, CloakBrowser, PlaywrightBrowser, get_browser


class FakeBrowser:
    def __init__(self) -> None:
        self.rendered: list[str] = []

    async def render(self, url: str, wait_for: str | None = None, timeout: float = 30.0) -> str:
        self.rendered.append(url)
        return f"<html>{url}</html>"

    async def post(self, url: str, payload: dict[str, Any], timeout: float = 30.0) -> str:
        return "{}"

    async def aclose(self) -> None:
        return None


def test_get_browser_defaults_to_playwright() -> None:
    browser = get_browser(Settings(browser_engine="playwright"))
    assert isinstance(browser, PlaywrightBrowser)


def test_get_browser_cloak() -> None:
    browser = get_browser(Settings(browser_engine="cloak"))
    assert isinstance(browser, CloakBrowser)


def test_get_browser_passes_headless() -> None:
    browser = get_browser(Settings(browser_engine="playwright", browser_headless=False))
    assert isinstance(browser, PlaywrightBrowser)
    assert browser._headless is False


def test_fake_browser_satisfies_protocol() -> None:
    assert isinstance(FakeBrowser(), BrowserFactory)


@pytest.mark.asyncio
async def test_aclose_on_never_started_is_noop() -> None:
    browser = PlaywrightBrowser()
    await browser.aclose()
    await browser.aclose()
    assert browser._browser is None
    assert browser._playwright is None


@pytest.mark.asyncio
async def test_cloak_missing_dependency_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "cloakbrowser":
            raise ImportError("No module named 'cloakbrowser'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    browser = CloakBrowser()
    with pytest.raises(RuntimeError, match="cloakbrowser"):
        await browser._start()
