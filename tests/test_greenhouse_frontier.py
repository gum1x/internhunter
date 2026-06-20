from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from internhunter.discovery.greenhouse_frontier import (
    FrontierResult,
    _last_high_water,
    _record_run,
    crawl_frontier,
)

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


async def test_frontier_does_not_skip_a_transient_failure(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    # 1 retry attempt so the 503 fails fast (no exponential backoff sleeps in the test).
    ctx.settings = ctx.settings.model_copy(update={"retry_max_attempts": 1})
    # id 103 ok, 102 a transient 503, 101 ok.
    ctx.responses[_EMBED.format(job_id=103)] = _redirect(103, "acme")
    ctx.responses[_EMBED.format(job_id=101)] = _redirect(101, "acme")
    ctx.responses[_EMBED.format(job_id=102)] = httpx.Response(503)
    ctx.responses[_JOB.format(token="acme", job_id=103)] = httpx.Response(
        200, text=json.dumps(_job(103, "ML Intern"))
    )
    ctx.responses[_JOB.format(token="acme", job_id=101)] = httpx.Response(
        200, text=json.dumps(_job(101, "ML Intern"))
    )

    result = await crawl_frontier(
        ctx, ctx.settings, window=3, known_tokens=set(), checkpoint=0, frontier=103
    )
    assert result.partial is True
    # Must NOT advance past the failed id 102 — next run re-probes it (high_water < 102).
    assert result.high_water == 101


async def test_frontier_advances_fully_on_clean_run(fake_fetch_context: Any) -> None:
    ctx = fake_fetch_context
    ctx.responses[_EMBED.format(job_id=60)] = _redirect(60, "acme")
    ctx.responses[_JOB.format(token="acme", job_id=60)] = httpx.Response(
        200, text=json.dumps(_job(60, "Intern"))
    )
    # 59 and 58 are clean 404 misses (no live job) — a definitive answer, safe to pass.
    result = await crawl_frontier(
        ctx, ctx.settings, window=3, known_tokens=set(), checkpoint=0, frontier=60
    )
    assert result.partial is False
    assert result.high_water == 60


def test_record_run_persists_checkpoint_and_finished_at(tmp_path: Path) -> None:
    from internhunter.core.db import get_session, init_db

    init_db(tmp_path / "t.db")
    session = get_session()
    _record_run(session, FrontierResult(resolved=2, high_water=7997555, partial=False))
    assert _last_high_water(session) == 7997555
    run = session.scalars(select_discovery_runs()).first()
    session.close()
    assert run is not None
    assert run.finished_at is not None
    assert run.status == "done"


def test_record_run_marks_partial(tmp_path: Path) -> None:
    from internhunter.core.db import get_session, init_db

    init_db(tmp_path / "t.db")
    session = get_session()
    _record_run(session, FrontierResult(high_water=10, partial=True))
    run = session.scalars(select_discovery_runs()).first()
    session.close()
    assert run is not None and run.status == "partial"


def select_discovery_runs():  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from internhunter.core.db import DiscoveryRun

    return select(DiscoveryRun)
