from __future__ import annotations

import gzip
import ipaddress
from typing import Any

import httpx
import pytest

from internhunter.config.settings import Settings
from internhunter.core.fetch import (
    SSRFError,
    _GuardedTransport,
    _ip_is_blocked,
    _trusted_hosts,
)


def test_ip_is_blocked_classes() -> None:
    blocked = ["127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "::1", "0.0.0.0"]
    allowed = ["8.8.8.8", "1.1.1.1", "140.82.112.3"]
    assert all(_ip_is_blocked(ipaddress.ip_address(ip)) for ip in blocked)
    assert not any(_ip_is_blocked(ipaddress.ip_address(ip)) for ip in allowed)


@pytest.mark.asyncio
async def test_guard_blocks_loopback_ip_literal() -> None:
    inner = httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
    client = httpx.AsyncClient(transport=_GuardedTransport(inner, set()))
    try:
        with pytest.raises(SSRFError):
            await client.get("http://127.0.0.1/latest/meta-data/")
        with pytest.raises(SSRFError):
            await client.get("http://169.254.169.254/")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_guard_allows_trusted_internal_host() -> None:
    # Operator-configured SearXNG on localhost must keep working.
    inner = httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
    client = httpx.AsyncClient(transport=_GuardedTransport(inner, {"127.0.0.1"}))
    try:
        resp = await client.get("http://127.0.0.1:8888/search")
        assert resp.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_guard_allows_public_ip() -> None:
    inner = httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
    client = httpx.AsyncClient(transport=_GuardedTransport(inner, set()))
    try:
        resp = await client.get("http://8.8.8.8/")
        assert resp.status_code == 200
    finally:
        await client.aclose()


def test_trusted_hosts_from_settings() -> None:
    s = Settings(searxng_url="http://localhost:8888", llm_base_url="http://10.0.0.9:8080")
    assert _trusted_hosts(s) == {"localhost", "10.0.0.9"}


@pytest.mark.asyncio
async def test_size_cap_rejects_oversized_body(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.settings.max_response_bytes = 100
    url = "https://big.example/data"
    ctx.responses[url] = httpx.Response(200, content=b"x" * 1000)
    with pytest.raises(httpx.HTTPError):
        await ctx.get_text(url)


@pytest.mark.asyncio
async def test_304_returns_cached_without_stale_encoding(tmp_path: Any) -> None:
    # Reproduces the gzip-corruption bug: a server sends real gzip on the 200, then a 304
    # echoing Content-Encoding: gzip. The reconstructed 200 must read cleanly.
    import asyncio

    from internhunter.core.fetch import FetchContext, HostLimiter, ResponseCache
    from tests.conftest import FakeRobotsCache

    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(
                200,
                content=gzip.compress(b"HELLO"),
                headers={"Content-Encoding": "gzip", "ETag": "abc"},
            )
        return httpx.Response(304, headers={"Content-Encoding": "gzip", "ETag": "abc"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "t.db")
    ctx = FetchContext(
        client=client,
        cache=ResponseCache(settings.cache_dir),
        robots=FakeRobotsCache(client, settings.default_user_agent),
        global_semaphore=asyncio.Semaphore(settings.http_concurrency),
        host_limiter=HostLimiter(settings.per_host_concurrency),
        settings=settings,
    )
    try:
        first = await ctx.get_text("https://x.example/data")
        assert first == "HELLO"
        second = await ctx.get_text("https://x.example/data")  # served from 304 path
        assert second == "HELLO"
        assert state["n"] == 2
    finally:
        await client.aclose()
