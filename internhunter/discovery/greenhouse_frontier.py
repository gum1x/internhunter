from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from internhunter.config.settings import Settings, get_settings
from internhunter.core.db import Board, DiscoveryRun, get_session, init_db, upsert_jobs
from internhunter.core.fetch import FetchContext, build_fetch_context
from internhunter.core.models import NormalizedJob
from internhunter.discovery.fingerprint import Detection, detect_from_url, detection_to_board_ref
from internhunter.discovery.merge import merge_boards
from internhunter.registry import load_boards
from internhunter.sources.base import BoardRef, RawPosting
from internhunter.sources.tier_a.greenhouse import GreenhouseSource

_EMBED = "https://boards.greenhouse.io/embed/job_app?token={job_id}"
_JOB = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?content=true"
_LIST = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
_METHOD = "greenhouse_frontier"
_SOURCE = GreenhouseSource()


@dataclass
class FrontierResult:
    probed: int = 0
    resolved: int = 0
    jobs: list[NormalizedJob] = field(default_factory=list)
    new_tokens: set[str] = field(default_factory=set)
    high_water: int = 0


def _last_high_water(session: Session) -> int:
    run = session.scalar(
        select(DiscoveryRun)
        .where(DiscoveryRun.method == _METHOD)
        .order_by(DiscoveryRun.id.desc())
    )
    if run is None:
        return 0
    value = (run.checkpoint or {}).get("high_water")
    return int(value) if isinstance(value, int) else 0


def _record_run(session: Session, result: FrontierResult) -> None:
    session.add(
        DiscoveryRun(
            method=_METHOD,
            boards_found=result.resolved,
            boards_new=len(result.new_tokens),
            checkpoint={"high_water": result.high_water},
            status="done",
        )
    )
    session.commit()


async def _anchor_frontier(ctx: FetchContext, tokens: list[str]) -> int:
    best = 0
    for token in tokens:
        try:
            data = await ctx.get_json(_LIST.format(token=token), respect_robots=False)
        except Exception:
            continue
        for job in data.get("jobs", []) if isinstance(data, dict) else []:
            job_id = job.get("id")
            if isinstance(job_id, int):
                best = max(best, job_id)
    return best


async def _resolve_token(ctx: FetchContext, job_id: int) -> str | None:
    try:
        location = await ctx.redirect_location(_EMBED.format(job_id=job_id))
    except Exception:
        return None
    if not location:
        return None
    detection = detect_from_url(location)
    return detection.token if detection is not None and detection.ats == "greenhouse" else None


async def _fetch_and_normalize(
    ctx: FetchContext, token: str, job_id: int
) -> NormalizedJob | None:
    try:
        job = await ctx.get_json(_JOB.format(token=token, job_id=job_id), respect_robots=False)
    except Exception:
        return None
    if not isinstance(job, dict) or not job.get("absolute_url"):
        return None
    ref = BoardRef(ats="greenhouse", token=token, company=job.get("company_name"))
    try:
        return _SOURCE.normalize(RawPosting(raw=job), ref)
    except Exception:
        return None


async def crawl_frontier(
    ctx: FetchContext,
    settings: Settings,
    *,
    window: int | None = None,
    known_tokens: set[str] | None = None,
    checkpoint: int = 0,
    frontier: int | None = None,
) -> FrontierResult:
    span = window if window is not None else settings.greenhouse_frontier_window
    known = known_tokens if known_tokens is not None else {
        r.token for r in load_boards(ats="greenhouse")
    }
    if frontier is None:
        seed = [r.token for r in load_boards(ats="greenhouse")][:12]
        frontier = await _anchor_frontier(ctx, seed)
    result = FrontierResult(high_water=max(checkpoint, frontier or 0))
    if not frontier:
        return result

    low = max(checkpoint, frontier - span)
    job_ids = list(range(frontier, low, -1))
    result.probed = len(job_ids)
    if not job_ids:
        return result

    sem = asyncio.Semaphore(max(1, settings.per_host_concurrency))

    async def probe(job_id: int) -> NormalizedJob | None:
        async with sem:
            token = await _resolve_token(ctx, job_id)
            if token is None:
                return None
            if token not in known:
                result.new_tokens.add(token)
            return await _fetch_and_normalize(ctx, token, job_id)

    for job in await asyncio.gather(*(probe(j) for j in job_ids)):
        if job is not None:
            result.resolved += 1
            result.jobs.append(job)
    return result


async def discover_greenhouse_frontier(
    ctx: FetchContext, settings: Settings, *, window: int | None = None
) -> FrontierResult:
    session = get_session()
    try:
        checkpoint = _last_high_water(session)
        known = set(
            session.scalars(select(Board.token).where(Board.ats == "greenhouse"))
        )
    finally:
        session.close()
    known |= {r.token for r in load_boards(ats="greenhouse")}

    result = await crawl_frontier(
        ctx, settings, window=window, known_tokens=known, checkpoint=checkpoint
    )

    if result.new_tokens:
        refs = [
            detection_to_board_ref(Detection("greenhouse", token, _EMBED.format(job_id="")))
            for token in sorted(result.new_tokens)
        ]
        merge_boards(refs)

    session = get_session()
    try:
        upsert_jobs(session, result.jobs)
        _record_run(session, result)
    finally:
        session.close()
    return result


def run_greenhouse_frontier(
    settings: Settings | None = None, window: int | None = None
) -> FrontierResult:
    resolved = settings or get_settings()
    init_db(resolved.db_path)

    async def _run() -> FrontierResult:
        async with build_fetch_context(resolved) as ctx:
            return await discover_greenhouse_frontier(ctx, resolved, window=window)

    return asyncio.run(_run())
