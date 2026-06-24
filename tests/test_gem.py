from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_b.gem import GemSource

FIXTURE = Path(__file__).parent / "fixtures" / "gem" / "jobs.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_gem_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = GemSource()
    ref = BoardRef(ats="gem", token="acme", company="Acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "gem"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.source_job_id == "job_8f21"
    assert intern.title == "Data Science Intern"
    assert intern.canonical_url == "https://jobs.gem.com/acme/data-science-intern"
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Data"
    assert intern.city == "San Francisco"
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_gem_poll_non_dict_response_yields_empty(fake_fetch_context: Any) -> None:
    from internhunter.sources.tier_b.gem import GemSource

    source = GemSource()
    ref = BoardRef(ats="gem", token="acme", company="Acme")
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, content=b"null", headers={"content-type": "application/json"}
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []
