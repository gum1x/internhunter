from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.personio import PersonioSource

FIXTURE = Path(__file__).parent / "fixtures" / "personio" / "jobs.xml"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_personio_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = PersonioSource()
    ref = BoardRef(ats="personio", token="acme", company="Acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, text=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "personio"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.source_job_id == "1840271"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == "https://acme.jobs.personio.de/job/1840271"
    assert intern.url_hash
    assert intern.job_uid
    assert intern.city == "Berlin"
    assert isinstance(intern.posted_at, datetime)
    assert "features in Python" in intern.description_text

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags

    senior = jobs[1]
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True
