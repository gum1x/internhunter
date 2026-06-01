from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from internhunter.core.fetch import FetchContext
from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.smartrecruiters import SmartRecruitersSource

_FIXTURES = Path(__file__).parent / "fixtures" / "smartrecruiters"
_TOKEN = "examplecompany"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def board_ref() -> BoardRef:
    return BoardRef(ats="smartrecruiters", token=_TOKEN, company="Example Company")


def _register_responses(ctx: FetchContext) -> None:
    jobs = _load("jobs.json")
    details = {
        "739ffc33-a17c-4b9b-9b3f-1b3c2c0d9a01": _load("detail_intern.json"),
        "84a2b6e1-1c4d-4e2f-8a77-2d9e0f1a2b02": _load("detail_senior.json"),
    }
    base = f"https://api.smartrecruiters.com/v1/companies/{_TOKEN}/postings"
    ctx.responses[f"{base}?limit=100&offset=0"] = httpx.Response(200, json=jobs)
    for posting in jobs["content"]:
        ctx.responses[f"{base}/{posting['id']}"] = httpx.Response(
            200, json=details[posting["id"]]
        )


@pytest.mark.asyncio
async def test_poll_yields_normalized_jobs(
    fake_fetch_context: FetchContext, board_ref: BoardRef
) -> None:
    _register_responses(fake_fetch_context)
    source = SmartRecruitersSource()

    jobs = await source.poll(board_ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = next(j for j in jobs if "Intern" in j.title)
    assert intern.ats == "smartrecruiters"
    assert intern.board_token == _TOKEN
    assert intern.company == "Example Company"
    assert intern.company_slug == "example-company"
    assert intern.source_job_id == "739ffc33-a17c-4b9b-9b3f-1b3c2c0d9a01"
    assert intern.canonical_url.endswith(intern.source_job_id)
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Engineering"
    assert intern.city == "San Francisco"
    assert intern.region == "CA"
    assert intern.posted_at is not None
    assert intern.posted_at.year == 2026
    assert intern.description_text
    assert "summer internship" in intern.description_text.lower()

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags


@pytest.mark.asyncio
async def test_non_intern_not_classified(
    fake_fetch_context: FetchContext, board_ref: BoardRef
) -> None:
    _register_responses(fake_fetch_context)
    source = SmartRecruitersSource()

    jobs = await source.poll(board_ref, fake_fetch_context)
    senior = next(j for j in jobs if j.title == "Senior Backend Engineer")

    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


def test_normalize_directly_classifies_intern(board_ref: BoardRef) -> None:
    from internhunter.sources.base import RawPosting

    jobs = _load("jobs.json")
    detail = _load("detail_intern.json")
    posting = jobs["content"][0]
    source = SmartRecruitersSource()

    job = source.normalize(RawPosting(raw=posting, detail=detail), board_ref)

    assert isinstance(job, NormalizedJob)
    assert job.is_internship is True
    assert job.internship_kind == "intern"
    assert job.rarity_score is None
    assert job.freshness_score is None
    assert job.discovery_score is None
    assert job.embedding_id is None
    assert job.times_seen_elsewhere == 0
