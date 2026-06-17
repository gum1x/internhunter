from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_a.pinpoint import PinpointSource

FIXTURE = Path(__file__).parent / "fixtures" / "pinpoint" / "postings.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_pinpoint_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = PinpointSource()
    ref = BoardRef(ats="pinpoint", token="acme", company="Acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "pinpoint"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.source_job_id == "118475"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == (
        "https://acme.pinpointhq.com/en/postings/25efc989-4fb4-4f3c-8b7c-d55ef484f54d"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Engineering"
    assert intern.employment_type == "internship"
    assert intern.city == "Berlin"
    assert intern.is_remote is False
    assert "build features in Python" in intern.description_text

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"
    assert "summer" in intern.level_tags

    senior = jobs[1]
    assert senior.source_job_id == "118999"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True
    assert senior.remote_scope == "fully_remote"


@pytest.mark.asyncio
async def test_pinpoint_poll_non_dict_response_yields_empty(fake_fetch_context: Any) -> None:
    source = PinpointSource()
    ref = BoardRef(ats="pinpoint", token="acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(
        200, content=b"null", headers={"content-type": "application/json"}
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []
