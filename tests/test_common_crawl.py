from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.common_crawl import (
    _cdx_url,
    discover_from_common_crawl,
    latest_crawl,
)


async def test_latest_crawl(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses["https://index.commoncrawl.org/collinfo.json"] = httpx.Response(
        200,
        text=json.dumps([{"id": "CC-MAIN-2099-99"}, {"id": "CC-MAIN-2098-50"}]),
    )
    assert await latest_crawl(ctx) == "CC-MAIN-2099-99"


async def test_discover_from_common_crawl(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    crawl = "CC-MAIN-2099-99"

    greenhouse_lines = [
        json.dumps({"url": "https://boards.greenhouse.io/acme"}),
        json.dumps({"url": "https://boards.greenhouse.io/acme"}),
        json.dumps({"url": "https://example.com/not-a-board"}),
    ]
    lever_lines = [
        json.dumps({"url": "https://jobs.lever.co/beta"}),
    ]

    ctx.responses[_cdx_url(crawl, "boards.greenhouse.io/*")] = httpx.Response(
        200, text="\n".join(greenhouse_lines) + "\n\n"
    )
    ctx.responses[_cdx_url(crawl, "jobs.lever.co/*")] = httpx.Response(
        200, text="\n".join(lever_lines)
    )

    detections = await discover_from_common_crawl(
        ctx, ats=["greenhouse", "lever"], crawl=crawl
    )
    keys = {(d.ats, d.token) for d in detections}
    assert ("greenhouse", "acme") in keys
    assert ("lever", "beta") in keys
    assert len(detections) == 2
