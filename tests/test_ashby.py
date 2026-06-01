from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from internhunter.config.settings import Settings
from internhunter.core.fetch import FetchContext, HostLimiter, ResponseCache, RobotsCache
from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.ashby import AshbySource

_FIXTURE = Path(__file__).parent / "fixtures" / "ashby" / "jobs.json"
_REF = BoardRef(ats="ashby", token="acme", company="Acme")


def _load_fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


class _AllowAllRobots(RobotsCache):
    async def allowed(self, url: str) -> bool:
        return True

    async def crawl_delay(self, url: str) -> float | None:
        return None


@pytest_asyncio.fixture
async def ashby_ctx(tmp_path: Any) -> AsyncIterator[FetchContext]:
    payload = _load_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.ashbyhq.com":
            return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "not found"})

    settings = Settings(cache_dir=tmp_path / "cache", db_path=tmp_path / "test.db")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx = FetchContext(
        client=client,
        cache=ResponseCache(settings.cache_dir),
        robots=_AllowAllRobots(client, settings.default_user_agent),
        global_semaphore=asyncio.Semaphore(settings.http_concurrency),
        host_limiter=HostLimiter(settings.per_host_concurrency),
        settings=settings,
    )
    try:
        yield ctx
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_poll_yields_normalized_jobs(ashby_ctx: FetchContext) -> None:
    source = AshbySource()

    jobs = await source.poll(_REF, ashby_ctx)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = next(job for job in jobs if "Intern" in job.title)
    assert intern.ats == "ashby"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.source_job_id == "5f8a3c21-7b2e-4d9a-9c1f-1a2b3c4d5e6f"
    assert intern.canonical_url.startswith("https://jobs.ashbyhq.com/acme/")
    assert intern.url_hash
    assert intern.job_uid
    assert intern.title_normalized == "software engineering intern summer 2026"
    assert intern.department == "Engineering"
    assert intern.location_raw == "San Francisco, CA, New York, NY"
    assert intern.posted_at is not None
    assert intern.posted_at.year == 2026
    assert intern.description_text

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags


@pytest.mark.asyncio
async def test_non_intern_classified_false(fake_fetch_context: Any) -> None:
    source = AshbySource()
    payload = _load_fixture()
    url = "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true"
    fake_fetch_context.responses[url] = httpx.Response(200, json=payload)

    jobs = await source.poll(_REF, fake_fetch_context)
    senior = next(job for job in jobs if "Senior" in job.title)

    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


def test_normalize_direct_on_fixture() -> None:
    from internhunter.sources.base import RawPosting

    source = AshbySource()
    payload = _load_fixture()
    job = source.normalize(RawPosting(raw=payload["jobs"][0]), _REF)

    assert isinstance(job, NormalizedJob)
    assert job.is_internship is True
    assert job.rarity_score is None
    assert job.freshness_score is None
    assert job.discovery_score is None
    assert job.embedding_id is None
    assert job.times_seen_elsewhere == 0
