from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time
import urllib.robotparser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from internhunter.core.browser import BrowserFactory

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from internhunter.config.settings import Settings, get_settings

_RETRY_STATUS = {403, 429, 500, 502, 503, 504}

# Headers that describe the wire encoding of the original body. They must be dropped when
# we synthesize a 200 from the (already-decoded) cached body on a 304, or httpx will try
# to re-decode plain bytes and raise DecodingError.
_HOP_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class SSRFError(httpx.HTTPError):
    """Raised when a request target resolves to a non-public / disallowed address."""


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _host_resolves_to_blocked(host: str, port: int) -> bool:
    """True if ``host`` is (or resolves to) a private/loopback/link-local/reserved IP.

    IP literals are checked directly. Hostnames are resolved via getaddrinfo and ALL
    returned addresses are checked (a single internal answer is enough to block). A
    resolution failure returns False — the real connection will then fail on its own,
    and we avoid turning transient DNS errors into security false-positives.
    """
    try:
        return _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port or None, type=socket.SOCK_STREAM
        )
    except OSError:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            if _ip_is_blocked(ipaddress.ip_address(addr)):
                return True
        except ValueError:
            continue
    return False


class _GuardedTransport(httpx.AsyncBaseTransport):
    """SSRF egress guard: blocks non-http(s) schemes and requests to internal addresses.

    Operator-configured hosts (e.g. self-hosted SearXNG, a local llama.cpp) are exempt via
    ``trusted_hosts`` so legitimate private targets keep working; everything else (URLs
    derived from crawled/untrusted content, and every redirect hop) is validated.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, trusted_hosts: set[str]) -> None:
        self._inner = inner
        self._trusted = trusted_hosts

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        scheme = request.url.scheme.lower()
        if scheme not in ("http", "https"):
            raise SSRFError(f"blocked non-http(s) scheme: {scheme!r}")
        host = (request.url.host or "").lower()
        if host not in self._trusted:
            port = request.url.port or (443 if scheme == "https" else 80)
            if await _host_resolves_to_blocked(host, port):
                raise SSRFError(f"blocked request to internal address: {host!r}")
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _trusted_hosts(settings: Settings) -> set[str]:
    """Operator-configured hosts that are allowed to be internal (SSRF allowlist)."""
    hosts: set[str] = set()
    for raw in (settings.searxng_url, settings.llm_base_url):
        if not raw:
            continue
        parsed = urlsplit(raw if "://" in raw else "//" + raw)
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    return hosts


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUS
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def _host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _cache_key(url: str, params: dict[str, Any] | None) -> str:
    raw = url
    if params:
        raw = raw + "?" + json.dumps(params, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class _CacheEntry:
    body: bytes
    etag: str | None
    last_modified: str | None


class ResponseCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.meta.json"

    def _body_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.body"

    def get(self, key: str) -> _CacheEntry | None:
        body_path = self._body_path(key)
        meta_path = self._meta_path(key)
        if not body_path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return _CacheEntry(
            body=body_path.read_bytes(),
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
        )

    def set(self, key: str, entry: _CacheEntry) -> None:
        self._body_path(key).write_bytes(entry.body)
        self._meta_path(key).write_text(
            json.dumps({"etag": entry.etag, "last_modified": entry.last_modified}),
            encoding="utf-8",
        )


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self._client = client
        self._user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = asyncio.Lock()

    async def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        host = _host_of(url)
        async with self._lock:
            if host in self._parsers:
                return self._parsers[host]
        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        parser: urllib.robotparser.RobotFileParser | None
        try:
            resp = await self._client.get(robots_url, timeout=10.0)
            if resp.status_code >= 400:
                parser = None
            else:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
        except httpx.HTTPError:
            parser = None
        async with self._lock:
            self._parsers[host] = parser
        return parser

    async def allowed(self, url: str) -> bool:
        parser = await self._parser_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)

    async def crawl_delay(self, url: str) -> float | None:
        parser = await self._parser_for(url)
        if parser is None:
            return None
        delay = parser.crawl_delay(self._user_agent)
        return float(delay) if delay is not None else None


class HostLimiter:
    def __init__(self, per_host_concurrency: int) -> None:
        self._per_host_concurrency = per_host_concurrency
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._next_allowed: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def semaphore(self, host: str) -> asyncio.Semaphore:
        async with self._lock:
            sem = self._semaphores.get(host)
            if sem is None:
                sem = asyncio.Semaphore(self._per_host_concurrency)
                self._semaphores[host] = sem
            return sem

    async def respect_delay(self, host: str, delay: float | None) -> None:
        if not delay:
            return
        async with self._lock:
            now = time.monotonic()
            wait_until = self._next_allowed.get(host, 0.0)
            sleep_for = max(0.0, wait_until - now)
            self._next_allowed[host] = max(now, wait_until) + delay
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


@dataclass
class FetchContext:
    client: httpx.AsyncClient
    cache: ResponseCache
    robots: RobotsCache
    global_semaphore: asyncio.Semaphore
    host_limiter: HostLimiter
    settings: Settings
    logger: Any = field(default=logger)
    browser: BrowserFactory | None = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        use_cache: bool = True,
        respect_robots: bool = True,
    ) -> httpx.Response:
        host = _host_of(url)

        if respect_robots and not await self.robots.allowed(url):
            self.logger.warning("robots.txt disallows {}", url)
            raise PermissionError(f"robots.txt disallows {url}")

        request_headers = dict(headers or {})
        cache_key = _cache_key(url, params)
        cached: _CacheEntry | None = None
        if use_cache and method == "GET":
            cached = self.cache.get(cache_key)
            if cached:
                if cached.etag:
                    request_headers.setdefault("If-None-Match", cached.etag)
                if cached.last_modified:
                    request_headers.setdefault("If-Modified-Since", cached.last_modified)

        delay = await self.robots.crawl_delay(url) if respect_robots else None
        host_sem = await self.host_limiter.semaphore(host)

        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self.settings.retry_max_attempts),
            wait=wait_exponential_jitter(initial=1.0, max=30.0),
            reraise=True,
        )
        async def _send() -> httpx.Response:
            async with self.global_semaphore:
                async with host_sem:
                    await self.host_limiter.respect_delay(host, delay)
                    response = await self.client.request(
                        method,
                        url,
                        params=params,
                        headers=request_headers,
                        json=json_body,
                    )
            if response.status_code in _RETRY_STATUS:
                response.raise_for_status()
            return response

        response = await _send()

        max_bytes = self.settings.max_response_bytes
        if max_bytes and len(response.content) > max_bytes:
            # Note: the body is already in memory here (non-streaming client); the cap
            # still prevents oversized responses from reaching the cache, parsers, and
            # regexes downstream — where the real amplification (ReDoS, disk-fill) lives.
            raise httpx.HTTPError(
                f"response from {url} exceeds {max_bytes}-byte cap"
            )

        if response.status_code == 304 and cached is not None:
            safe_headers = {
                k: v
                for k, v in response.headers.items()
                if k.lower() not in _HOP_HEADERS
            }
            return httpx.Response(
                status_code=200,
                content=cached.body,
                request=response.request,
                headers=safe_headers,
            )

        if use_cache and method == "GET" and response.status_code == 200:
            self.cache.set(
                cache_key,
                _CacheEntry(
                    body=response.content,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                ),
            )

        response.raise_for_status()
        return response

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        respect_robots: bool = True,
    ) -> Any:
        response = await self._request(
            "GET",
            url,
            params=params,
            headers=headers,
            use_cache=use_cache,
            respect_robots=respect_robots,
        )
        return response.json()

    async def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        respect_robots: bool = True,
    ) -> str:
        response = await self._request(
            "GET",
            url,
            params=params,
            headers=headers,
            use_cache=use_cache,
            respect_robots=respect_robots,
        )
        return response.text

    async def post_json(
        self,
        url: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self._request(
            "POST",
            url,
            params=params,
            headers=headers,
            json_body=json_body,
            use_cache=False,
        )
        return response.json()

    async def redirect_location(
        self, url: str, *, headers: dict[str, str] | None = None
    ) -> str | None:
        """Single GET that does NOT follow redirects; returns the raw Location header (None
        for a definitive 2xx/4xx, e.g. a 404 = no resource). Retries/raises on transient
        statuses (429/5xx) so callers can tell "absent" from "throttled". robots is
        intentionally bypassed: only the 3xx Location carries the data we need."""
        host = _host_of(url)
        host_sem = await self.host_limiter.semaphore(host)

        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self.settings.retry_max_attempts),
            wait=wait_exponential_jitter(initial=1.0, max=30.0),
            reraise=True,
        )
        async def _send() -> httpx.Response:
            async with self.global_semaphore:
                async with host_sem:
                    resp = await self.client.get(
                        url, headers=headers, follow_redirects=False
                    )
            if resp.status_code in _RETRY_STATUS:
                resp.raise_for_status()
            return resp

        response = await _send()
        if response.is_redirect:
            location = response.headers.get("location")
            return location if isinstance(location, str) else None
        return None


@asynccontextmanager
async def build_fetch_context(settings: Settings | None = None) -> AsyncIterator[FetchContext]:
    resolved = settings or get_settings()
    headers = {"User-Agent": resolved.default_user_agent}
    transport = _GuardedTransport(
        httpx.AsyncHTTPTransport(proxy=resolved.http_proxy or None),
        _trusted_hosts(resolved),
    )
    async with httpx.AsyncClient(
        timeout=resolved.request_timeout,
        headers=headers,
        follow_redirects=True,
        # proxy is applied inside _GuardedTransport's inner AsyncHTTPTransport, so it must
        # not also be passed here (httpx forbids transport= together with proxy=).
        transport=transport,
    ) as client:
        browser: BrowserFactory | None = None
        if resolved.enable_browser:
            from internhunter.core.browser import get_browser

            browser = get_browser(resolved)
        ctx = FetchContext(
            client=client,
            cache=ResponseCache(resolved.cache_dir),
            robots=RobotsCache(client, resolved.default_user_agent),
            global_semaphore=asyncio.Semaphore(resolved.http_concurrency),
            host_limiter=HostLimiter(resolved.per_host_concurrency),
            settings=resolved,
            browser=browser,
        )
        try:
            yield ctx
        finally:
            if browser is not None:
                await browser.aclose()
