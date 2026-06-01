from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from internhunter.config.settings import Settings
from internhunter.core.db import Base
from internhunter.core.fetch import FetchContext, HostLimiter, ResponseCache, RobotsCache


class FakeRobotsCache(RobotsCache):
    async def allowed(self, url: str) -> bool:
        return True

    async def crawl_delay(self, url: str) -> float | None:
        return None


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest_asyncio.fixture
async def fake_fetch_context(tmp_path: Any) -> AsyncIterator[FetchContext]:
    responses: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key in responses:
            return responses[key]
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "test.db")
    ctx = FetchContext(
        client=client,
        cache=ResponseCache(settings.cache_dir),
        robots=FakeRobotsCache(client, settings.default_user_agent),
        global_semaphore=asyncio.Semaphore(settings.http_concurrency),
        host_limiter=HostLimiter(settings.per_host_concurrency),
        settings=settings,
    )
    ctx.responses = responses
    try:
        yield ctx
    finally:
        await client.aclose()
