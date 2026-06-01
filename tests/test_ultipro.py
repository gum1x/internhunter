from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_c.ultipro import UltiproSource

FIXTURE = Path(__file__).parent / "fixtures" / "ultipro" / "jobs.xml"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_ultipro_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = UltiproSource()
    ref = BoardRef(ats="ultipro", token="ACM1001/abcd", company="Acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, text=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "ultipro"
    assert intern.board_token == "ACM1001/abcd"
    assert intern.company == "Acme"
    assert intern.source_job_id == "2001"
    assert intern.title == "Software Engineering Intern"
    assert (
        intern.canonical_url
        == "https://recruiting.ultipro.com/ACM1001/JobBoard/abcd/OpportunityDetail?opportunityId=2001"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.city == "Berlin"
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "2002"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_ultipro_poll_malformed_token_yields_empty(fake_fetch_context: Any) -> None:
    source = UltiproSource()
    ref = BoardRef(ats="ultipro", token="ACM1001", company="Acme")

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []
