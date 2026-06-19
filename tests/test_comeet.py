from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_b.comeet import ComeetSource

FIXTURE = Path(__file__).parent / "fixtures" / "comeet" / "jobs.html"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_comeet_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    source = ComeetSource()
    ref = BoardRef(ats="comeet", token="tripleten/98.008")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(200, text=_load_fixture())

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "comeet"
    assert intern.board_token == "tripleten/98.008"
    assert intern.company == "TripleTen"
    assert intern.source_job_id == "AC.001"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == (
        "https://www.comeet.com/jobs/tripleten/98.008/software-engineering-intern/AC.001"
    )
    assert intern.url_hash
    assert intern.job_uid
    assert intern.department == "Engineering"
    assert intern.employment_type == "Internship"
    assert intern.location_raw == "Berlin, Germany"
    assert intern.city == "Berlin"
    assert intern.is_remote is False
    assert isinstance(intern.posted_at, datetime)
    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "AC.002"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_comeet_poll_missing_data_yields_empty(fake_fetch_context: Any) -> None:
    source = ComeetSource()
    ref = BoardRef(ats="comeet", token="tripleten/98.008")
    url = source.board_url(ref)
    fake_fetch_context.responses[url] = httpx.Response(
        200, text="<html><body>no data</body></html>"
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []


_TITLE_WITH_BRACKET = "Build arrays like x[1]; ship fast"
_COMEET_HTML_BRACKET = (
    "<html><body><script>"
    'var COMPANY_POSITIONS_DATA = [{"name": '
    f'"{_TITLE_WITH_BRACKET}", "uid": "AC.010", '
    '"url_active_page": "https://www.comeet.com/jobs/x/1/a/AC.010", '
    '"workplace_type": "Hybrid"}, '
    '{"name": "Backend Engineer", "uid": "AC.011", '
    '"url_active_page": "https://www.comeet.com/jobs/x/1/b/AC.011", '
    '"workplace_type": "Remote"}];'
    "</script></body></html>"
)


@pytest.mark.asyncio
async def test_comeet_poll_handles_bracket_in_title(fake_fetch_context: Any) -> None:
    # A position name containing `];` must not truncate the balanced JSON.
    source = ComeetSource()
    ref = BoardRef(ats="comeet", token="x/1")
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, text=_COMEET_HTML_BRACKET
    )

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert jobs[0].title == _TITLE_WITH_BRACKET


@pytest.mark.asyncio
async def test_comeet_poll_workplace_type(fake_fetch_context: Any) -> None:
    source = ComeetSource()
    ref = BoardRef(ats="comeet", token="x/1")
    fake_fetch_context.responses[source.board_url(ref)] = httpx.Response(
        200, text=_COMEET_HTML_BRACKET
    )

    jobs = await source.poll(ref, fake_fetch_context)

    hybrid = jobs[0]
    assert hybrid.is_remote is True
    assert hybrid.remote_scope == "hybrid"
    remote = jobs[1]
    assert remote.is_remote is True
