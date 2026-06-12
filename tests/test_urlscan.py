from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.urlscan import (
    _search_url,
    _workday_token,
    discover_from_urlscan,
)


def test_workday_token_parses_tenant_and_site() -> None:
    assert (
        _workday_token("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
        == "nvidia/NVIDIAExternalCareerSite"
    )
    assert _workday_token("https://acme.wd1.myworkdayjobs.com/External/job/x") == "acme/External"
    assert _workday_token("https://boards.greenhouse.io/acme") is None


async def test_discover_from_urlscan(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    gh = {
        "results": [
            {"task": {"url": "https://boards.greenhouse.io/acme/jobs/1"}},
            {"page": {"url": "https://boards.greenhouse.io/acme/jobs/2"}},
            {"task": {"url": "https://example.com/not-a-board"}},
        ],
        "has_more": False,
    }
    wd = {
        "results": [
            {"task": {"url": "https://beta.wd5.myworkdayjobs.com/en-US/Careers"}},
        ],
        "has_more": False,
    }
    ctx.responses[_search_url("domain:greenhouse.io")] = httpx.Response(
        200, text=json.dumps(gh)
    )
    ctx.responses[_search_url("domain:myworkdayjobs.com")] = httpx.Response(
        200, text=json.dumps(wd)
    )

    detections = await discover_from_urlscan(ctx, ats=["greenhouse", "workday"])
    keys = {(d.ats, d.token) for d in detections}
    assert ("greenhouse", "acme") in keys
    assert ("workday", "beta/Careers") in keys
    assert len(detections) == 2
