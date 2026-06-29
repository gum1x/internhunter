from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_c.paylocity import PaylocitySource

FIXTURE = Path(__file__).parent / "fixtures" / "paylocity" / "jobs.html"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_paylocity_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = PaylocitySource()
    ref = BoardRef(ats="paylocity", token="GUID123")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, text=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "paylocity"
    assert intern.board_token == "GUID123"
    assert intern.company == "GUID123"
    assert intern.source_job_id == "JB-1001"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == (
        "https://recruiting.paylocity.com/Recruiting/Jobs/Details/JB-1001"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.location_raw == "Berlin, BE"
    assert intern.city == "Berlin"
    assert isinstance(intern.posted_at, datetime)
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "JB-2002"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_paylocity_poll_non_dict_response_yields_empty(fake_fetch_context: Any) -> None:
    source = PaylocitySource()
    ref = BoardRef(ats="paylocity", token="GUID123")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(
        200, content=b"null", headers={"content-type": "application/json"}
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []


@pytest.mark.asyncio
async def test_paylocity_poll_handles_brace_in_description(fake_fetch_context: Any) -> None:
    # A description containing `};` must not truncate the balanced JSON.
    source = PaylocitySource()
    ref = BoardRef(ats="paylocity", token="GUID123")
    html = (
        "<html><body><script>"
        'window.pageData = {"Jobs": [{"JobId": "JB-9001", '
        '"JobTitle": "Software Intern", '
        '"Description": "Write code like func() {}; then deploy.", '
        '"LocationName": "Remote", "IsRemote": true}, '
        '{"JobId": "JB-9002", "JobTitle": "Engineer", '
        '"Description": "Build things.", "LocationName": "Berlin"}]};'
        "</script></body></html>"
    )
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(200, text=html)

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert jobs[0].source_job_id == "JB-9001"
    assert "{};" in jobs[0].description_text
    assert jobs[1].source_job_id == "JB-9002"
