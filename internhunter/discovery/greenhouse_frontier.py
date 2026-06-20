from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
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


# A probe outcome: "ok" (resolved a live job), "miss" (definitively no live job at this id:
# clean 404 / no redirect), or "error" (transient: timeout/429/5xx/network).
_TRANSIENT = (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError)


@dataclass
class FrontierResult:
    probed: int = 0
    resolved: int = 0
    jobs: list[NormalizedJob] = field(default_factory=list)
    new_tokens: set[str] = field(default_factory=set)
    high_water: int = 0
    partial: bool = False


def _last_high_water(session: Session) -> int:
    run = session.scalar(
        select(DiscoveryRun)
        .where(DiscoveryRun.method == _METHOD, DiscoveryRun.status != "running")
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
            finished_at=datetime.now(UTC),
            status="partial" if result.partial else "done",
        )
    )
    session.commit()


async def _anchor_frontier(ctx: FetchContext, tokens: list[str]) -> int:
    best = 0
    for token in tokens:
        try:
            # Never cached: the anchor must reflect the live max id, or fresh jobs above a
            # stale cached value would sit above the frontier and never be probed.
            data = await ctx.get_json(
                _LIST.format(token=token), respect_robots=False, use_cache=False
            )
        except Exception:
            continue
        for job in data.get("jobs", []) if isinstance(data, dict) else []:
            job_id = job.get("id")
            if isinstance(job_id, int):
                best = max(best, job_id)
    return best


async def _resolve_token(ctx: FetchContext, job_id: int) -> tuple[str, str | None]:
    try:
        location = await ctx.redirect_location(_EMBED.format(job_id=job_id))
    except _TRANSIENT:
        return "error", None
    except Exception:
        return "error", None
    if not location:
        return "miss", None
    detection = detect_from_url(location)
    if detection is None or detection.ats != "greenhouse":
        return "miss", None
    return "ok", detection.token


async def _fetch_and_normalize(
    ctx: FetchContext, token: str, job_id: int
) -> tuple[str, NormalizedJob | None]:
    try:
        job = await ctx.get_json(_JOB.format(token=token, job_id=job_id), respect_robots=False)
    except httpx.HTTPStatusError as exc:
        return ("miss" if exc.response.status_code == 404 else "error"), None
    except _TRANSIENT:
        return "error", None
    except Exception:
        return "error", None
    if not isinstance(job, dict) or not job.get("absolute_url"):
        return "miss", None
    ref = BoardRef(ats="greenhouse", token=token, company=job.get("company_name"))
    try:
        return "ok", _SOURCE.normalize(RawPosting(raw=job), ref)
    except Exception:
        return "miss", None


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
    span = max(1, min(span, settings.greenhouse_frontier_max_window))
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

    async def probe(job_id: int) -> tuple[int, str, NormalizedJob | None]:
        status, token = await _resolve_token(ctx, job_id)
        if status != "ok" or token is None:
            return job_id, status, None
        if token not in known:
            result.new_tokens.add(token)
        job_status, job = await _fetch_and_normalize(ctx, token, job_id)
        return job_id, job_status, job

    outcomes = await asyncio.gather(*(probe(j) for j in job_ids))
    errored = [job_id for job_id, status, _ in outcomes if status == "error"]
    for _job_id, status, job in outcomes:
        if status == "ok" and job is not None:
            result.resolved += 1
            result.jobs.append(job)

    if errored:
        # Never advance the checkpoint past a transiently-failed id, or that id (a possibly
        # brand-new posting) is lost forever — the embed endpoint is per-id, not re-pollable.
        # Advance only to just below the lowest failure so the next run re-probes it.
        result.high_water = max(checkpoint, min(errored) - 1)
        result.partial = True
    else:
        result.high_water = max(checkpoint, frontier)
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
            detection_to_board_ref(
                Detection("greenhouse", token, f"https://boards.greenhouse.io/{token}")
            )
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
