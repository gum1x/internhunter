from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_b.breezy import BreezyHrSource

FIXTURE = Path(__file__).parent / "fixtures" / "breezy" / "positions.json"


def _load_fixture() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_breezy_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = BreezyHrSource()
    ref = BoardRef(ats="breezy", token="acme", company="Acme")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "breezy"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.source_job_id == "f1a2b3c4"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == "https://acme.breezy.hr/p/f1a2b3c4-software-engineering-intern"
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Engineering"
    assert intern.employment_type == "Internship"
    assert intern.city == "Berlin"
    assert isinstance(intern.posted_at, datetime)
    assert "build features in Python" in intern.description_text

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_breezy_poll_non_list_response_yields_empty(fake_fetch_context: Any) -> None:
    from internhunter.sources.tier_b.breezy import BreezyHrSource

    source = BreezyHrSource()
    ref = BoardRef(ats="breezy", token="acme", company="Acme")
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, json={"error": "boom"}
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []
