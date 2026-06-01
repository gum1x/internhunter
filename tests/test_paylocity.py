from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_c.paylocity import PaylocitySource

FIXTURE = Path(__file__).parent / "fixtures" / "paylocity" / "jobs.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_paylocity_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = PaylocitySource()
    ref = BoardRef(ats="paylocity", token="GUID123")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

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
        "https://recruiting.paylocity.com/recruiting/jobs/JB-1001/GUID123"
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
