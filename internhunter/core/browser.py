from __future__ import annotations

import random
from typing import Any, Protocol, runtime_checkable

from internhunter.config.settings import Settings, get_settings

# Rotate over a few recent-Chrome UAs / common viewports / plausible timezones so repeated
# renders don't present an identical, easily-fingerprinted browser.
_USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
)
_VIEWPORTS = (
    {"width": 1280, "height": 800},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
)
_TIMEZONES = ("America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin")
_USER_AGENT = _USER_AGENTS[0]
_VIEWPORT = _VIEWPORTS[0]
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-infobars",
]
_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


@runtime_checkable
class BrowserFactory(Protocol):
    async def render(
        self, url: str, wait_for: str | None = None, timeout: float = 30.0
    ) -> str: ...

    async def post(
        self, url: str, payload: dict[str, Any], timeout: float = 30.0
    ) -> str: ...

    async def aclose(self) -> None: ...


class PlaywrightBrowser:
    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None

    async def _start(self) -> Any:
        from playwright.async_api import async_playwright

        return await async_playwright().start()

    async def _ensure(self) -> Any:
        if self._browser is None:
            self._playwright = await self._start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=_LAUNCH_ARGS,
            )
        return self._browser

    async def _new_context(self) -> Any:
        browser = await self._ensure()
        context = await browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            viewport=random.choice(_VIEWPORTS),
            locale="en-US",
            timezone_id=random.choice(_TIMEZONES),
        )
        await context.add_init_script(_INIT_SCRIPT)
        return context

    async def render(
        self, url: str, wait_for: str | None = None, timeout: float = 30.0
    ) -> str:
        timeout_ms = timeout * 1000.0
        context = await self._new_context()
        try:
            page = await context.new_page()
            try:
                await page.goto(
                    url, timeout=timeout_ms, wait_until="domcontentloaded"
                )
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=timeout_ms)
                content: str = await page.content()
                return content
            finally:
                await page.close()
        finally:
            await context.close()

    async def post(
        self, url: str, payload: dict[str, Any], timeout: float = 30.0
    ) -> str:
        context = await self._new_context()
        try:
            response = await context.request.post(
                url, data=payload, timeout=timeout * 1000.0
            )
            text: str = await response.text()
            return text
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


class CloakBrowser(PlaywrightBrowser):
    async def _start(self) -> Any:
        try:
            import cloakbrowser
        except ImportError as exc:
            raise RuntimeError(
                "browser_engine='cloak' requires the 'cloakbrowser' package, "
                "which is not installed. Install it (pip install cloakbrowser) "
                "or set INTERNHUNTER_BROWSER_ENGINE=playwright."
            ) from exc

        entrypoint = getattr(cloakbrowser, "async_cloak", None)
        if entrypoint is None:
            raise RuntimeError(
                "The installed 'cloakbrowser' package does not expose the "
                "expected 'async_cloak' entrypoint. The integration must be "
                "updated to match the installed cloakbrowser API, or set "
                "INTERNHUNTER_BROWSER_ENGINE=playwright."
            )
        return await entrypoint().start()


def get_browser(settings: Settings | None = None) -> BrowserFactory:
    resolved = settings or get_settings()
    if resolved.browser_engine == "cloak":
        return CloakBrowser(headless=resolved.browser_headless)
    return PlaywrightBrowser(headless=resolved.browser_headless)
