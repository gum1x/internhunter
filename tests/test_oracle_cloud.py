from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_c.oracle_cloud import OracleCloudSource

FIXTURE = Path(__file__).parent / "fixtures" / "oracle_cloud" / "jobs.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_oracle_cloud_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = OracleCloudSource()
    ref = BoardRef(ats="oracle_cloud", token="acme", extra={"site": "CX_1001"})
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, json=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "oracle_cloud"
    assert intern.board_token == "acme"
    assert intern.company == "acme"
    assert intern.source_job_id == "REQ12345"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == (
        "https://acme.fa.oraclecloud.com/hcmUI/CandidateExperience/en/"
        "sites/CX_1001/job/REQ12345"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.city == "Austin"
    assert isinstance(intern.posted_at, datetime)
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "REQ67890"
    assert senior.is_internship is False
    assert senior.internship_kind is None
