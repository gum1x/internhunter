from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from internhunter.core.fetch import FetchContext
from internhunter.core.models import EmploymentType, NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.lever import LeverSource

_FIXTURE = Path(__file__).parent / "fixtures" / "lever" / "jobs.json"


def _load_fixture() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_lever_poll_yields_normalized_jobs(fake_fetch_context: FetchContext) -> None:
    source = LeverSource()
    ref = BoardRef(ats="lever", token="acme", company="Acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = next(job for job in jobs if "Intern" in job.title)
    assert intern.ats == "lever"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.company_slug == "acme"
    assert intern.source_job_id == "f2a1c3de-1111-4a2b-9c3d-aaaaaaaaaaaa"
    assert intern.canonical_url.startswith("https://jobs.lever.co/acme/")
    assert intern.url_hash
    assert intern.job_uid
    assert intern.title_normalized == "software engineering intern summer 2026"
    assert intern.department == "Engineering"
    assert intern.employment_type == EmploymentType.internship.value
    assert intern.location_raw == "San Francisco, CA"
    assert intern.city == "San Francisco"
    assert intern.region == "CA"
    assert intern.description_text
    assert isinstance(intern.posted_at, datetime)
    assert intern.is_rolling is True

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags
    assert "paid" in intern.level_tags

    senior = next(job for job in jobs if job.title == "Senior Backend Engineer")
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


def test_lever_normalize_intern_classification() -> None:
    source = LeverSource()
    ref = BoardRef(ats="lever", token="acme", company="Acme")
    from internhunter.sources.base import RawPosting

    raw = RawPosting(raw=_load_fixture()[0])
    job = source.normalize(raw, ref)

    assert isinstance(job, NormalizedJob)
    assert job.is_internship is True
    assert job.internship_kind == "intern"
    assert job.title == "Software Engineering Intern, Summer 2026"
