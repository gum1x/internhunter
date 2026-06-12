from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_c.workday import WorkdaySource

FIXTURE = Path(__file__).parent / "fixtures" / "workday" / "jobs.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_workday_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = WorkdaySource()
    ref = BoardRef(ats="workday", token="acme/Careers", extra={"dc": "wd5"})
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "workday"
    assert intern.board_token == "acme/Careers"
    assert intern.company == "acme"
    assert intern.source_job_id == "Software-Engineering-Intern_R-12345"
    assert intern.title == "Software Engineering Intern"
    assert (
        intern.canonical_url
        == "https://acme.wd5.myworkdayjobs.com/Careers/job/Berlin/Software-Engineering-Intern_R-12345"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.location_raw == "Berlin, Germany"
    assert intern.city == "Berlin"
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_workday_probes_datacenter_when_dc_unknown(fake_fetch_context: Any) -> None:
    source = WorkdaySource()
    ref = BoardRef(ats="workday", token="acme/Careers")
    wd5_url = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
    fake_fetch_context.responses[wd5_url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert jobs[0].canonical_url.startswith("https://acme.wd5.myworkdayjobs.com/Careers")
