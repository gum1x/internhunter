from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_b.teamtailor import (
    _MAX_DETAIL_FETCHES,
    TeamtailorSource,
    _extract_job_posting,
)

FIXTURES = Path(__file__).parent / "fixtures" / "teamtailor"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_teamtailor_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = TeamtailorSource()
    ref = BoardRef(ats="teamtailor", token="sweep")

    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, text=_load("jobs.html")
    )
    fake_fetch_context.responses[
        "https://sweep.teamtailor.com/jobs/7700798-data-engineer-intern"
    ] = httpx.Response(200, text=_load("job_7700798.html"))
    fake_fetch_context.responses[
        "https://sweep.teamtailor.com/jobs/7816129-senior-fullstack-engineer"
    ] = httpx.Response(200, text=_load("job_7816129.html"))

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "teamtailor"
    assert intern.board_token == "sweep"
    assert intern.company == "SWEEP"
    assert intern.source_job_id == "7700798"
    assert intern.title == "Data Engineer Intern"
    assert intern.canonical_url == (
        "https://sweep.teamtailor.com/jobs/7700798-data-engineer-intern"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.employment_type == "INTERN"
    assert intern.location_raw == "Paris, France, FR"
    assert intern.city == "Paris"
    assert "Sweep is hiring" in intern.description_text
    assert isinstance(intern.posted_at, datetime)
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "7816129"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.city == "London"


@pytest.mark.asyncio
async def test_teamtailor_poll_missing_listing_yields_empty(fake_fetch_context: Any) -> None:
    source = TeamtailorSource()
    ref = BoardRef(ats="teamtailor", token="sweep")
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, text="<html><body>no jobs</body></html>"
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []


def _job_detail(job_id: str) -> str:
    return (
        '<html><head><script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Role", '
        f'"identifier": {{"@type": "PropertyValue", "value": "{job_id}"}}}}'
        "</script></head><body></body></html>"
    )


@pytest.mark.asyncio
async def test_teamtailor_caps_and_dedupes_detail_fetches(fake_fetch_context: Any) -> None:
    # Build a listing with more unique jobs than the cap, plus duplicate links
    # (same numeric id, different slug) that must be deduped.
    source = TeamtailorSource()
    ref = BoardRef(ats="teamtailor", token="sweep")
    fetched: list[str] = []

    n_unique = _MAX_DETAIL_FETCHES + 5
    links = []
    for i in range(n_unique):
        url = f"https://sweep.teamtailor.com/jobs/{1000 + i}-role-{i}"
        links.append(f'<a href="{url}"></a>')
        # duplicate link for the same numeric id with a different slug
        dup = f"https://sweep.teamtailor.com/jobs/{1000 + i}-role-dup-{i}"
        links.append(f'<a href="{dup}"></a>')
        fake_fetch_context.responses[url] = httpx.Response(200, text=_job_detail(str(1000 + i)))
        fake_fetch_context.responses[dup] = httpx.Response(200, text=_job_detail(str(1000 + i)))
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, text="<html><body>" + "".join(links) + "</body></html>"
    )

    original_get_text = fake_fetch_context.get_text

    async def tracking_get_text(url: str, **kwargs: Any) -> str:
        if "/jobs/" in url:
            fetched.append(url)
        return await original_get_text(url, **kwargs)

    fake_fetch_context.get_text = tracking_get_text

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(fetched) == _MAX_DETAIL_FETCHES
    assert len(jobs) == _MAX_DETAIL_FETCHES


def test_extract_job_posting_from_list() -> None:
    html = (
        '<script type="application/ld+json">'
        '[{"@type": "Organization"}, {"@type": "JobPosting", "title": "X"}]'
        "</script>"
    )
    posting = _extract_job_posting(html)
    assert posting is not None
    assert posting["title"] == "X"


def test_extract_job_posting_from_graph() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@graph": [{"@type": "WebPage"}, {"@type": "JobPosting", "title": "Y"}]}'
        "</script>"
    )
    posting = _extract_job_posting(html)
    assert posting is not None
    assert posting["title"] == "Y"


@pytest.mark.asyncio
async def test_teamtailor_unescapes_description(fake_fetch_context: Any) -> None:
    source = TeamtailorSource()
    ref = BoardRef(ats="teamtailor", token="sweep")
    job_url = "https://sweep.teamtailor.com/jobs/5000-intern"
    detail = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Intern", '
        '"description": "&lt;p&gt;Join the &amp; team&lt;/p&gt;", '
        '"identifier": {"@type": "PropertyValue", "value": "5000"}}'
        "</script></head><body></body></html>"
    )
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, text=f'<html><body><a href="{job_url}"></a></body></html>'
    )
    fake_fetch_context.responses[job_url] = httpx.Response(200, text=detail)

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 1
    text = jobs[0].description_text
    assert "Join the & team" in text
    assert "&lt;" not in text and "&amp;" not in text
