from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_b.teamtailor import TeamtailorSource

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
