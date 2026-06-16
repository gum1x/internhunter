from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.config.settings import Settings
from internhunter.discovery.github_code import _search_url, discover_from_github_code


async def test_disabled_by_default_makes_no_http_call(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    calls: list[str] = []
    original = ctx.client.request

    async def spy(*args: Any, **kwargs: Any) -> httpx.Response:
        calls.append(str(args[1] if len(args) > 1 else kwargs.get("url")))
        return await original(*args, **kwargs)

    ctx.client.request = spy  # type: ignore[method-assign]

    settings = ctx.settings  # github_code_search defaults to False
    assert settings.github_code_search is False
    detections = await discover_from_github_code(ctx, settings)
    assert detections == []
    assert calls == []


async def test_enabled_without_token_is_noop(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    settings = Settings(
        cache_dir=ctx.settings.cache_dir,
        db_path=ctx.settings.db_path,
        github_code_search=True,
        github_token="",
    )
    detections = await discover_from_github_code(ctx, settings)
    assert detections == []


async def test_enabled_with_token_parses_detections(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    settings = Settings(
        cache_dir=ctx.settings.cache_dir,
        db_path=ctx.settings.db_path,
        github_code_search=True,
        github_token="ghp_x",
    )
    payload = {
        "items": [
            {"html_url": "https://github.com/acme/repo/blob/main/x.md"},
            {
                "html_url": "https://github.com/acme/repo/blob/main/links.txt",
                "text_matches": [
                    {"fragment": "apply at https://boards.greenhouse.io/acme/jobs/1"}
                ],
            },
        ]
    }
    ctx.responses[_search_url("boards.greenhouse.io")] = httpx.Response(
        200, text=json.dumps(payload)
    )

    detections = await discover_from_github_code(
        ctx, settings, ats=["greenhouse"]
    )
    keys = {(d.ats, d.token) for d in detections}
    assert ("greenhouse", "acme") in keys
