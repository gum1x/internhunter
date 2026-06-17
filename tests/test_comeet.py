from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_b.comeet import ComeetSource

FIXTURE = Path(__file__).parent / "fixtures" / "comeet" / "jobs.html"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_comeet_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = ComeetSource()
    ref = BoardRef(ats="comeet", token="tripleten/98.008")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, text=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "comeet"
    assert intern.board_token == "tripleten/98.008"
    assert intern.company == "TripleTen"
    assert intern.source_job_id == "AC.001"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == (
        "https://www.comeet.com/jobs/tripleten/98.008/software-engineering-intern/AC.001"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Engineering"
    assert intern.employment_type == "Internship"
    assert intern.location_raw == "Berlin, Germany"
    assert intern.city == "Berlin"
    assert intern.is_remote is False
    assert isinstance(intern.posted_at, datetime)
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "AC.002"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_comeet_poll_missing_data_yields_empty(fake_fetch_context: Any) -> None:
    source = ComeetSource()
    ref = BoardRef(ats="comeet", token="tripleten/98.008")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(
        200, text="<html><body>no data</body></html>"
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []
