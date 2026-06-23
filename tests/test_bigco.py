from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.bigco import (
    _fetch_amazon,
    _fetch_apple,
    _fetch_google,
    _make_fetcher,
)


async def test_fetch_amazon(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[
        "https://www.amazon.jobs/en/search.json?base_query=intern&result_limit=100"
    ] = httpx.Response(
        200,
        text=json.dumps(
            {
                "jobs": [
                    {
                        "title": "SDE Intern",
                        "job_path": "/en/jobs/123/sde-intern",
                        "normalized_location": "Seattle, WA",
                        "posted_date": "2026-05-01",
                    }
                ]
            }
        ),
    )
    jobs = await _fetch_amazon(ctx)
    assert len(jobs) == 1
    assert jobs[0].company == "Amazon"
    assert jobs[0].url == "https://www.amazon.jobs/en/jobs/123/sde-intern"
    assert jobs[0].source == "bigco:amazon"


async def test_fetch_google(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[
        "https://careers.google.com/api/v3/search/?q=intern&page_size=100"
    ] = httpx.Response(
        200,
        text=json.dumps(
            {
                "jobs": [
                    {
                        "title": "Engineering Intern",
                        "apply_url": "https://www.google.com/about/careers/jobs/1",
                        "locations": [{"display": "Mountain View, CA"}],
                        "created": "2026-05-01",
                    }
                ]
            }
        ),
    )
    jobs = await _fetch_google(ctx)
    assert jobs[0].company == "Google"
    assert jobs[0].location == "Mountain View, CA"


async def test_fetch_apple_uses_post(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses["https://jobs.apple.com/api/role/search"] = httpx.Response(
        200,
        text=json.dumps(
            {
                "res": {
                    "searchResults": [
                        {
                            "postingTitle": "Software Engineering Intern",
                            "positionId": "200",
                            "locations": [{"name": "Cupertino, CA"}],
                            "postDateInGMT": "2026-05-01",
                        }
                    ]
                }
            }
        ),
    )
    jobs = await _fetch_apple(ctx)
    assert jobs[0].url == "https://jobs.apple.com/en-us/details/200"
    assert jobs[0].source == "bigco:apple"


async def test_make_fetcher_isolates_failures(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    # Only amazon responds; the others 404 -> must not raise, amazon still returned.
    ctx.responses[
        "https://www.amazon.jobs/en/search.json?base_query=intern&result_limit=100"
    ] = httpx.Response(200, text=json.dumps({"jobs": [{"title": "Intern", "job_path": "/p"}]}))
    fetcher = _make_fetcher(ctx.settings)
    jobs = await fetcher(ctx)
    assert any(j.source == "bigco:amazon" for j in jobs)
