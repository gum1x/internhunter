from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from internhunter.core.fetch import FetchContext
from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.greenhouse import GreenhouseSource

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse" / "jobs.json"


@pytest.fixture
def source() -> GreenhouseSource:
    return GreenhouseSource()


@pytest.fixture
def ref() -> BoardRef:
    return BoardRef(ats="greenhouse", token="acmecorp", company="Acme Corp")


@pytest.mark.asyncio
async def test_poll_yields_normalized_jobs(
    source: GreenhouseSource, ref: BoardRef, fake_fetch_context: FetchContext
) -> None:
    body = FIXTURE.read_text(encoding="utf-8")
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, content=body, headers={"Content-Type": "application/json"}
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = next(j for j in jobs if "Intern" in j.title)
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags
    assert intern.ats == "greenhouse"
    assert intern.board_token == "acmecorp"
    assert intern.company == "Acme Corp"
    assert intern.company_slug == "acme-corp"
    assert intern.source_job_id == "4011223"
    assert intern.canonical_url == "https://boards.greenhouse.io/acmecorp/jobs/4011223"
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Engineering"
    assert intern.city == "San Francisco"
    assert intern.region == "CA"
    assert intern.is_remote is False
    assert "Summer 2026 internship" in intern.description_text
    assert "<strong>" not in intern.description_text
    assert intern.posted_at is not None
    assert intern.posted_at.year == 2026
    assert intern.is_rolling is True

    senior = next(j for j in jobs if j.title == "Senior Backend Engineer")
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


def test_normalize_classifies_intern_row(source: GreenhouseSource, ref: BoardRef) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    from internhunter.sources.base import RawPosting

    job = source.normalize(RawPosting(raw=payload["jobs"][0]), ref)
    assert isinstance(job, NormalizedJob)
    assert job.is_internship is True
    assert job.rarity_score is None
    assert job.freshness_score is None
    assert job.discovery_score is None
    assert job.embedding_id is None
    assert job.times_seen_elsewhere == 0
