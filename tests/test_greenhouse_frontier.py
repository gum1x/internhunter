from __future__ import annotations

import json
from typing import Any

import httpx

from internhunter.discovery.greenhouse_frontier import crawl_frontier

_EMBED = "https://boards.greenhouse.io/embed/job_app?token={job_id}"
_JOB = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?content=true"


def _job(job_id: int, title: str) -> dict[str, Any]:
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
        "location": {"name": "Remote"},
        "content": "Join the team and build things.",
        "company_name": "Acme",
        "updated_at": "2026-06-10T00:00:00Z",
        "first_published": "2026-06-10T00:00:00Z",
        "departments": [{"name": "Engineering"}],
    }


def _redirect(job_id: int, token: str) -> httpx.Response:
    target = f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={job_id}"
    return httpx.Response(301, headers={"location": target})


async def test_frontier_resolves_tokens_and_normalizes(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_EMBED.format(job_id=103)] = _redirect(103, "acme")
    ctx.responses[_EMBED.format(job_id=101)] = _redirect(101, "acme")
    ctx.responses[_JOB.format(token="acme", job_id=103)] = httpx.Response(
        200, text=json.dumps(_job(103, "Software Engineering Intern"))
    )
    ctx.responses[_JOB.format(token="acme", job_id=101)] = httpx.Response(
        200, text=json.dumps(_job(101, "Senior Staff Engineer"))
    )

    result = await crawl_frontier(
        ctx, ctx.settings, window=3, known_tokens=set(), checkpoint=0, frontier=103
    )

    assert result.probed == 3  # 103, 102 (a 404 miss), 101
    assert result.resolved == 2
    assert "acme" in result.new_tokens
    intern = next(j for j in result.jobs if "Intern" in j.title)
    assert intern.is_internship is True
    assert intern.ats == "greenhouse"
    assert intern.board_token == "acme"
    assert intern.is_remote is True


async def test_frontier_skips_known_tokens(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_EMBED.format(job_id=50)] = _redirect(50, "acme")
    ctx.responses[_JOB.format(token="acme", job_id=50)] = httpx.Response(
        200, text=json.dumps(_job(50, "ML Intern"))
    )

    result = await crawl_frontier(
        ctx, ctx.settings, window=1, known_tokens={"acme"}, checkpoint=0, frontier=50
    )

    assert result.resolved == 1  # the job is still ingested
    assert result.new_tokens == set()  # but the board is already known


async def test_frontier_respects_checkpoint(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    result = await crawl_frontier(
        ctx, ctx.settings, window=100, known_tokens=set(), checkpoint=200, frontier=200
    )
    assert result.probed == 0  # nothing newer than the checkpoint
