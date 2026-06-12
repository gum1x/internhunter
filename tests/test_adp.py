from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from internhunter.core.models import NormalizedJob
from internhunter.sources.base import BoardRef
from internhunter.sources.tier_c.adp import AdpSource

FIXTURE = Path(__file__).parent / "fixtures" / "adp" / "jobs.html"


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class FakeBrowser:
    def __init__(self, html: str = "", json_text: str = "{}") -> None:
        self._html = html
        self._json = json_text

    async def render(self, url: str, wait_for: str | None = None, timeout: float = 30.0) -> str:  # noqa: ASYNC109
        return self._html

    async def post(self, url: str, payload: dict[str, Any], timeout: float = 30.0) -> str:  # noqa: ASYNC109
        return self._json

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_adp_poll_yields_normalized_jobs(fake_fetch_context: Any) -> None:
    fake_fetch_context.browser = FakeBrowser(html=_load_fixture())
    source = AdpSource()
    ref = BoardRef(ats="adp", token="acme", company="Acme")

    jobs = await source.poll(ref, fake_fetch_context)

    assert len(jobs) == 2
    assert all(isinstance(job, NormalizedJob) for job in jobs)

    intern = jobs[0]
    assert intern.ats == "adp"
    assert intern.board_token == "acme"
    assert intern.company == "Acme"
    assert intern.source_job_id == "SE-INTERN-001"
    assert intern.title == "Software Engineering Intern"
    assert intern.canonical_url == "https://jobs.adp.com/company/acme/job/SE-INTERN-001"
    assert intern.url_hash
    assert intern.job_uid
    assert intern.city == "Berlin"

    assert intern.is_internship is True
    assert intern.internship_kind == "intern"

    senior = jobs[1]
    assert senior.source_job_id == "SR-BACKEND-042"
    assert senior.is_internship is False
    assert senior.internship_kind is None
    assert senior.is_remote is True


@pytest.mark.asyncio
async def test_adp_poll_returns_empty_without_browser(fake_fetch_context: Any) -> None:
    fake_fetch_context.browser = None
    source = AdpSource()
    ref = BoardRef(ats="adp", token="acme", company="Acme")

    jobs = await source.poll(ref, fake_fetch_context)

    assert jobs == []
