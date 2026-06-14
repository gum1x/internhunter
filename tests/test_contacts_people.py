from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.contacts.classify import classify_title_heuristic, role_priority
from internhunter.contacts.people.searxng_people import (
    _search_url,
    discover_people_searxng,
    parse_result,
)


def test_parse_result_extracts_name_title_url() -> None:
    person = parse_result(
        "Jane Doe - University Recruiter at Acme | LinkedIn",
        "https://www.linkedin.com/in/jane-doe-123",
    )
    assert person is not None
    assert person.full_name == "Jane Doe"
    assert "University Recruiter" in (person.title or "")
    assert person.linkedin_url == "https://www.linkedin.com/in/jane-doe-123"


def test_parse_result_handles_missing_title() -> None:
    person = parse_result("Bob Smith", "https://www.linkedin.com/in/bob-smith")
    assert person is not None
    assert person.full_name == "Bob Smith"


async def test_discover_people_searxng_dedupes(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    base = "https://searx.local"
    company = "Acme"
    payload = {
        "results": [
            {
                "title": "Jane Doe - Recruiter at Acme | LinkedIn",
                "url": "https://www.linkedin.com/in/jane-doe",
            },
            {
                "title": "Jane Doe - Recruiter at Acme | LinkedIn",
                "url": "https://www.linkedin.com/in/jane-doe",
            },
            {
                "title": "Max Pen - Engineer at Acme | LinkedIn",
                "url": "https://www.linkedin.com/in/max-pen",
            },
        ]
    }
    from internhunter.contacts.people.searxng_people import _DORKS

    for dork in _DORKS:
        url = _search_url(base, dork.format(company=company))
        ctx.responses[url] = httpx.Response(200, text=json.dumps(payload))

    people = await discover_people_searxng(ctx, base, company)
    keys = {p.dedup_key() for p in people}
    assert len(people) == len(keys)
    names = {p.full_name for p in people}
    assert "Jane Doe" in names
    assert "Max Pen" in names


def test_classify_heuristic() -> None:
    assert classify_title_heuristic("Senior University Recruiter") == "university_recruiter"
    assert classify_title_heuristic("Technical Recruiter") == "technical_recruiter"
    assert classify_title_heuristic("Software Engineer") == "ic_engineer"
    assert classify_title_heuristic("Engineering Manager") == "eng_manager"
    assert classify_title_heuristic(None) == "other"


def test_role_priority_ranks_recruiters_first() -> None:
    assert role_priority("university_recruiter") > role_priority("ic_engineer")
    assert role_priority("recruiter") > role_priority("other")
