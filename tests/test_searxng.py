from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.searxng import _search_url, discover_from_searxng


async def test_discover_from_searxng(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    base_url = "https://searx.local"
    queries = ["site:boards.greenhouse.io intern", "site:jobs.lever.co intern"]

    greenhouse_results = {
        "results": [
            {"url": "https://boards.greenhouse.io/acme", "title": "Acme"},
            {"url": "https://boards.greenhouse.io/acme", "title": "Acme dup"},
            {"url": "https://example.com/not-a-board", "title": "Noise"},
        ]
    }
    lever_results = {
        "results": [
            {"url": "https://jobs.lever.co/beta", "title": "Beta"},
        ]
    }

    ctx.responses[_search_url(base_url, queries[0])] = httpx.Response(
        200, text=json.dumps(greenhouse_results)
    )
    ctx.responses[_search_url(base_url, queries[1])] = httpx.Response(
        200, text=json.dumps(lever_results)
    )

    detections = await discover_from_searxng(ctx, base_url, queries=queries)
    keys = {(d.ats, d.token) for d in detections}
    assert ("greenhouse", "acme") in keys
    assert ("lever", "beta") in keys
    assert len(detections) == 2
