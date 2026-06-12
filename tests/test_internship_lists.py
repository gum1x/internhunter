from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.internship_lists import (
    _LISTS,
    board_refs,
    entry_to_job,
    fetch_list_entries,
)


def _entry(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "abc",
        "company_name": "Acme",
        "title": "Software Engineering Intern",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "locations": ["New York, NY"],
        "date_posted": 1760568838,
        "active": True,
        "is_visible": True,
    }
    base.update(kw)
    return base


async def test_fetch_list_entries_filters_inactive(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    payload = [
        _entry(id="1"),
        _entry(id="2", active=False),
        _entry(id="3", is_visible=False),
        _entry(id="4"),
    ]
    ctx.responses[_LISTS[0]] = httpx.Response(200, text=json.dumps(payload))
    ctx.responses[_LISTS[1]] = httpx.Response(404, json={})
    entries = await fetch_list_entries(ctx)
    assert [e["id"] for e in entries] == ["1", "4"]


def test_entry_to_job_builds_internship() -> None:
    job = entry_to_job(_entry())
    assert job is not None
    assert job.is_internship is True
    assert job.title == "Software Engineering Intern"
    assert job.company == "Acme"
    assert job.ats == "greenhouse"
    assert job.board_token == "acme"
    assert job.canonical_url == "https://boards.greenhouse.io/acme/jobs/1"
    assert job.city == "New York"
    assert job.posted_at is not None and job.posted_at.year == 2025


def test_entry_to_job_non_ats_url_falls_back() -> None:
    job = entry_to_job(_entry(url="https://acme.com/jobs/intern", company_name="Acme Co"))
    assert job is not None
    assert job.ats == "listing"
    assert job.company_slug == "acme-co"


def test_entry_to_job_skips_missing_url() -> None:
    assert entry_to_job(_entry(url="")) is None


def test_board_refs_extracts_ats_boards() -> None:
    refs = board_refs([_entry(id="1"), _entry(id="2"), _entry(url="https://acme.com/jobs")])
    assert [(r.ats, r.token) for r in refs] == [("greenhouse", "acme")]
