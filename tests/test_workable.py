from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from internhunter.core.fetch import FetchContext
from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.workable import WorkableSource

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "workable"


def _load(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def workable_context(fake_fetch_context: FetchContext) -> FetchContext:
    widget = _load("jobs.json")
    detail = _load("job_detail.json")
    fake_fetch_context.responses[
        "https://apply.workable.com/api/v1/widget/accounts/acme?details=true"
    ] = httpx.Response(200, json=widget)
    fake_fetch_context.responses[
        "https://apply.workable.com/api/v1/accounts/acme/jobs/ABC123DEF4"
    ] = httpx.Response(200, json=detail)
    return fake_fetch_context


@pytest.mark.asyncio
async def test_workable_poll_yields_normalized_jobs(workable_context: FetchContext) -> None:
    source = WorkableSource()
    ref = BoardRef(ats="workable", token="acme", company="Acme Corp")

    jobs = await source.poll(ref, workable_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    by_id = {job.source_job_id: job for job in jobs}
    intern = by_id["ABC123DEF4"]
    senior = by_id["XYZ789GHI0"]

    assert intern.ats == "workable"
    assert intern.board_token == "acme"
    assert intern.title == "Software Engineering Intern - Summer 2026"
    assert intern.title_normalized == "software engineering intern summer 2026"
    assert intern.canonical_url == "https://apply.workable.com/acme/j/ABC123DEF4/"
    assert intern.url_hash and intern.job_uid
    assert intern.department == "Engineering"
    assert intern.city == "San Francisco"
    assert intern.region == "California"
    assert intern.country == "United States"
    assert intern.is_remote is False

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags
    assert "paid" in intern.level_tags

    assert "summer internship program" in intern.description_text.lower()
    assert intern.posted_at is not None and intern.posted_at.year == 2026
    assert intern.updated_at is not None
    assert intern.deadline_at is not None and intern.deadline_at.month == 3

    assert intern.rarity_score is None
    assert intern.freshness_score is None
    assert intern.discovery_score is None
    assert intern.embedding_id is None
    assert intern.times_seen_elsewhere == 0

    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True
    assert senior.remote_scope == "fully_remote"


@pytest.mark.asyncio
async def test_workable_detail_404_does_not_fail_board(
    fake_fetch_context: FetchContext,
) -> None:
    widget = _load("jobs.json")
    fake_fetch_context.responses[
        "https://apply.workable.com/api/v1/widget/accounts/acme?details=true"
    ] = httpx.Response(200, json=widget)

    source = WorkableSource()
    ref = BoardRef(ats="workable", token="acme", company="Acme Corp")

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    intern = next(job for job in jobs if job.source_job_id == "ABC123DEF4")
    assert intern.is_internship is True
    assert intern.description_text == ""
