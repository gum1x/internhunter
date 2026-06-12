from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.hackernews import (
    _item_url,
    _search_url,
    discover_from_hackernews,
    latest_hiring_thread_id,
    recent_hiring_thread_ids,
)


async def test_discover_multiple_months(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_search_url(9)] = httpx.Response(
        200,
        text=json.dumps(
            {
                "hits": [
                    {"objectID": "100", "title": "Ask HN: Who is hiring? (June 2026)"},
                    {"objectID": "101", "title": "Ask HN: Who wants to be hired? (June 2026)"},
                    {"objectID": "102", "title": "Ask HN: Who is hiring? (May 2026)"},
                ]
            }
        ),
    )
    ctx.responses[_item_url(100)] = httpx.Response(
        200, text=json.dumps({"children": [{"text": "https://jobs.lever.co/aco", "children": []}]})
    )
    ctx.responses[_item_url(102)] = httpx.Response(
        200,
        text=json.dumps(
            {"children": [{"text": "https://jobs.ashbyhq.com/bco", "children": []}]}
        ),
    )
    assert await recent_hiring_thread_ids(ctx, 3) == [100, 102]
    dets = await discover_from_hackernews(ctx, months=3)
    keys = {(d.ats, d.token) for d in dets}
    assert ("lever", "aco") in keys
    assert ("ashby", "bco") in keys


async def test_latest_hiring_thread_id(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_search_url()] = httpx.Response(
        200, text=json.dumps({"hits": [{"objectID": "42"}]})
    )
    assert await latest_hiring_thread_id(ctx) == 42


async def test_discover_from_hackernews(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_search_url()] = httpx.Response(
        200, text=json.dumps({"hits": [{"objectID": "42"}]})
    )
    item = {
        "children": [
            {
                "text": "We are hiring! Apply at https://boards.greenhouse.io/acme",
                "children": [
                    {
                        "text": "Also see https://jobs.ashbyhq.com/gamma/roles",
                        "children": [],
                    }
                ],
            },
            {
                "text": "Join us https://jobs.lever.co/beta",
                "children": [],
            },
        ]
    }
    ctx.responses[_item_url(42)] = httpx.Response(200, text=json.dumps(item))

    detections = await discover_from_hackernews(ctx)
    keys = {(d.ats, d.token) for d in detections}
    assert ("greenhouse", "acme") in keys
    assert ("lever", "beta") in keys
    assert ("ashby", "gamma") in keys


async def test_discover_handles_deeply_nested_thread(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    node: dict[str, Any] = {"text": "https://jobs.lever.co/deepco", "children": []}
    for _ in range(2000):
        node = {"text": "reply", "children": [node]}
    ctx.responses[_item_url(9)] = httpx.Response(200, text=json.dumps({"children": [node]}))

    detections = await discover_from_hackernews(ctx, thread_id=9, max_comments=5000)
    assert ("lever", "deepco") in {(d.ats, d.token) for d in detections}


async def test_discover_dedupes(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    item = {
        "children": [
            {"text": "https://boards.greenhouse.io/acme", "children": []},
            {"text": "https://boards.greenhouse.io/acme", "children": []},
        ]
    }
    ctx.responses[_item_url(7)] = httpx.Response(200, text=json.dumps(item))

    detections = await discover_from_hackernews(ctx, thread_id=7)
    assert len(detections) == 1
    assert detections[0].ats == "greenhouse"
    assert detections[0].token == "acme"
